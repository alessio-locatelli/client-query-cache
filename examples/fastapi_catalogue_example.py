# /// script
# requires-python = ">=3.14"
# dependencies = ["client-query-cache", "fastapi>=0.143.0", "httpx2>=2.13.1"]
#
# [tool.uv.sources]
# client-query-cache = { path = "..", editable = true }
# ///

import os
from contextlib import asynccontextmanager
from functools import partial
from time import monotonic, sleep
from typing import TYPE_CHECKING, Annotated, Literal, TypedDict, cast

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.testclient import TestClient
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveInt,
    TypeAdapter,
)
from pymongo import AsyncMongoClient, ReadPreference
from pymongo.errors import InvalidOperation
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from client_query_cache.asynchronous import (
    BypassReason,
    CacheManager,
    StreamHealthStatus,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

    from anyio.from_thread import BlockingPortal
    from pymongo.asynchronous.collection import AsyncCollection

    from client_query_cache.asynchronous import CachedCollection, CacheSnapshot

DATABASE_NAME = "client_query_cache_example_fastapi_catalogue"
DEFAULT_MONGODB_URI = "mongodb://localhost:27017/?directConnection=true"
PAGE_URL = "/products?offset=1&page_size=2"
NonEmptyStr = Annotated[str, Field(min_length=1)]
TenantId = Literal["north", "south"]
DEPLOYMENTS: tuple[tuple[bool, NonEmptyStr], ...] = (
    (False, "north description revised directly"),
    (True, "updated north description"),
    (False, "north description revised after rollback"),
)


class ProductDocument(TypedDict):
    _id: NonEmptyStr
    tenant_id: TenantId
    product_id: NonEmptyStr
    description: NonEmptyStr
    rank: PositiveInt


class Product(BaseModel):
    product_id: NonEmptyStr
    description: NonEmptyStr
    rank: PositiveInt


class DescriptionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: NonEmptyStr


class Principal(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: TenantId
    can_write: bool


class CatalogueRepository:
    def __init__(
        self, manager: CacheManager[ProductDocument], *, content_cache_enabled: bool
    ) -> None:
        self.manager = manager
        self.raw = manager.client[DATABASE_NAME].get_collection(
            "products",
            read_preference=ReadPreference.PRIMARY,
            read_concern=ReadConcern("majority"),
            write_concern=WriteConcern(w="majority"),
        )
        self.content: (
            AsyncCollection[ProductDocument] | CachedCollection[ProductDocument]
        ) = (
            manager.get_cached_collection(self.raw)
            if content_cache_enabled
            else self.raw
        )

    async def describe(self, tenant_id: TenantId, product_id: NonEmptyStr) -> Product:
        document = await self.content.find_one(
            {"tenant_id": tenant_id, "product_id": product_id}
        )
        if document is None:
            raise HTTPException(status_code=404, detail="Product not found")
        return Product.model_validate(document)

    async def page(
        self, tenant_id: TenantId, offset: NonNegativeInt, page_size: PositiveInt
    ) -> tuple[Product, ...]:
        documents = await (
            self.content.find({"tenant_id": tenant_id})
            .sort([("rank", 1), ("product_id", 1)])
            .skip(offset)
            .limit(page_size)
            .to_list()
        )
        return tuple(Product.model_validate(document) for document in documents)

    async def update_description(
        self, tenant_id: TenantId, product_id: NonEmptyStr, update: DescriptionUpdate
    ) -> Product:
        predicate = {"tenant_id": tenant_id, "product_id": product_id}
        async with self.manager.client.start_session(
            causal_consistency=True
        ) as session:
            mutation = await self.raw.update_one(
                predicate,
                {"$set": {"description": update.description}},
                session=session,
            )
            if mutation.matched_count == 0:
                raise HTTPException(status_code=404, detail="Product not found")
            document = await self.raw.find_one(predicate, session=session)
        if document is None:
            # A concurrent deletion may follow the acknowledged update.
            raise HTTPException(status_code=404, detail="Product no longer exists")
        return Product.model_validate(document)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    mongodb_uri = os.getenv("MONGODB_URI", DEFAULT_MONGODB_URI)
    async with (
        AsyncMongoClient[ProductDocument](mongodb_uri) as client,
        CacheManager(client) as manager,
    ):
        app.state.repository = CatalogueRepository(
            manager,
            content_cache_enabled=cast("bool", app.state.content_cache_enabled),
        )
        yield


def authenticated_principal() -> Principal:
    raise HTTPException(status_code=401, detail="Trusted authentication required")


def catalogue_repository(request: Request) -> CatalogueRepository:
    return cast("CatalogueRepository", request.app.state.repository)


router = APIRouter()
TrustedPrincipal = Annotated[Principal, Depends(authenticated_principal)]
Repository = Annotated[CatalogueRepository, Depends(catalogue_repository)]


@router.get("/products/{product_id}")
async def describe_product(
    product_id: NonEmptyStr, principal: TrustedPrincipal, repository: Repository
) -> Product:
    return await repository.describe(principal.tenant_id, product_id)


@router.get("/products")
async def product_page(
    principal: TrustedPrincipal,
    repository: Repository,
    offset: Annotated[int, Query(ge=0)] = 0,
    page_size: Annotated[int, Query(ge=1, le=50)] = 10,
) -> tuple[Product, ...]:
    return await repository.page(principal.tenant_id, offset, page_size)


@router.patch("/products/{product_id}")
async def update_product(
    product_id: NonEmptyStr,
    update: DescriptionUpdate,
    principal: TrustedPrincipal,
    repository: Repository,
) -> Product:
    if not principal.can_write:
        raise HTTPException(
            status_code=403, detail="Catalogue write permission required"
        )
    return await repository.update_description(principal.tenant_id, product_id, update)


def create_app(*, content_cache_enabled: bool = False) -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    app.state.content_cache_enabled = content_cache_enabled
    app.include_router(router)
    return app


def demonstration_principal(
    x_demo_principal: Annotated[Literal["alice", "bob"] | None, Header()] = None,
) -> Principal:
    if x_demo_principal == "alice":
        return Principal(tenant_id="north", can_write=True)
    if x_demo_principal == "bob":
        return Principal(tenant_id="south", can_write=False)
    return authenticated_principal()


async def seed_catalogue(repository: CatalogueRepository) -> None:
    await repository.manager.client.drop_database(DATABASE_NAME)
    await repository.raw.create_index(
        [("tenant_id", 1), ("product_id", 1)], unique=True
    )
    await repository.raw.create_index(
        [("tenant_id", 1), ("rank", 1), ("product_id", 1)]
    )
    await repository.raw.insert_many(
        tuple(
            ProductDocument(
                _id=f"{tenant_id}-{product_id}",
                tenant_id=tenant_id,
                product_id=product_id,
                description=f"{tenant_id} {product_id}",
                rank=rank,
            )
            for tenant_id in ("north", "south")
            for product_id, rank in (("last", 3), ("first", 1), ("shared", 2))
        )
    )


async def session_bound_read(repository: CatalogueRepository) -> Product:
    async with repository.manager.client.start_session() as session:
        document = await repository.content.find_one(
            {"tenant_id": "north", "product_id": "shared"}, session=session
        )
    return Product.model_validate(document)


def checked_item(http: TestClient, owner: Literal["alice", "bob"]) -> Product:
    response = http.get("/products/shared", headers={"X-Demo-Principal": owner})
    if response.status_code != 200:
        raise SystemExit("catalogue item request failed")
    return Product.model_validate_json(response.text)


def checked_page(
    http: TestClient, owner: Literal["alice", "bob"]
) -> tuple[Product, ...]:
    response = http.get(PAGE_URL, headers={"X-Demo-Principal": owner})
    if response.status_code != 200:
        raise SystemExit("catalogue page request failed")
    return TypeAdapter(tuple[Product, ...]).validate_json(response.text)


def recorded_outcome(before: CacheSnapshot, after: CacheSnapshot) -> str:
    match (
        after.hits - before.hits,
        after.misses - before.misses,
        after.bypasses - before.bypasses,
    ):
        case (0, 0, 0):
            return "direct"
        case (1, 0, 0):
            return "hit"
        case (0, 1, 0):
            return "miss"
        case (0, 0, bypasses) if bypasses > 0:
            return "bypass"
        case counts:
            return f"hit, miss and bypass counts {counts}"


def outcome_of[T](
    manager: CacheManager[ProductDocument], read: Callable[[], T]
) -> tuple[T, str]:
    before = manager.snapshot()  # pytriage: TR5 - Sample before the read.
    return read(), recorded_outcome(before, manager.snapshot())


def observed[T](
    manager: CacheManager[ProductDocument],
    behavior: str,
    expected: str,
    read: Callable[[], T],
) -> T:
    content, outcome = outcome_of(manager, read)
    if outcome != expected:
        message = f"{behavior} recorded {outcome}, expected {expected}"
        raise SystemExit(message)
    return content


def session_bypasses(snapshot: CacheSnapshot) -> int:
    return next(
        record.count
        for record in snapshot.bypass_reasons
        if record.reason is BypassReason.SESSION
    )


def report(label: str, manager: CacheManager[ProductDocument]) -> None:
    snapshot = manager.snapshot()
    reasons = ", ".join(
        f"{record.reason} {record.count}"
        for record in snapshot.bypass_reasons
        if record.count
    )
    print(
        f"{label}: hits {snapshot.hits}, misses {snapshot.misses}, "
        f"bypasses {snapshot.bypasses} ({reasons or 'none'}), "
        f"entries {snapshot.entry_count}, resident bytes {snapshot.used_bytes} "
        f"of {snapshot.shared_budget_bytes}, "
        f"stream {manager.stream_health_snapshot(DATABASE_NAME).status}"
    )


def run_scenario(
    http: TestClient,
    repository: CatalogueRepository,
    portal: BlockingPortal,
    *,
    content_cache_enabled: bool,
    north_description: NonEmptyStr,
    revision: NonEmptyStr,
) -> None:
    manager = repository.manager
    deployment_start = manager.snapshot()  # pytriage: TR11 - Capture first.
    cold, warm = ("miss", "hit") if content_cache_enabled else ("direct", "direct")
    for method in ("GET", "PATCH"):
        response = http.request(
            method, "/products/shared", json={"description": "unauthenticated"}
        )
        if response.status_code != 401:
            raise SystemExit("missing identity was not rejected")
    if manager.snapshot() != deployment_start:
        raise SystemExit("unauthenticated request reached cached storage")

    identities: tuple[tuple[Literal["alice", "bob"], TenantId], ...] = (
        ("alice", "north"),
        ("bob", "south"),
    )
    for owner, tenant_id in identities:
        expected = Product(
            product_id="shared",
            description=north_description
            if tenant_id == "north"
            else f"{tenant_id} shared",
            rank=2,
        )
        expected_page = (
            expected,
            Product(product_id="last", description=f"{tenant_id} last", rank=3),
        )
        for read in (checked_item, checked_page):
            for attempt in range(5):
                content = observed(
                    manager,
                    f"{read.__name__} for {owner}",
                    warm if attempt else cold,
                    partial(read, http, owner),
                )
                if content != (expected if read is checked_item else expected_page):
                    raise SystemExit("item or page tenant isolation failed")

    for page_size in (0, 51):
        if (
            http.get(
                f"/products?page_size={page_size}",
                headers={"X-Demo-Principal": "alice"},
            ).status_code
            != 422
        ):
            raise SystemExit("page size bounds were not enforced")
    if (
        http.get("/products/missing", headers={"X-Demo-Principal": "alice"}).status_code
        != 404
    ):
        raise SystemExit("missing product was not reported")

    for url in ("/products/shared?tenant_id=south", f"{PAGE_URL}&tenant_id=south"):
        response = observed(
            manager,
            "tenant selector request",
            warm,
            partial(http.get, url, headers={"X-Demo-Principal": "alice"}),
        )
        if response.status_code != 200 or "south" in response.text:
            raise SystemExit("client tenant selector replaced authenticated identity")
    reads_before = manager.snapshot()  # pytriage: TR11 - Capture first.
    for owner, payload, expected_status in (
        ("bob", {"description": "forbidden"}, 403),
        ("alice", {"description": "tampered", "tenant_id": "south"}, 422),
    ):
        if (
            http.patch(
                "/products/shared", json=payload, headers={"X-Demo-Principal": owner}
            ).status_code
            != expected_status
        ):
            raise SystemExit("forbidden write or body tenant selector was accepted")
    if manager.snapshot() != reads_before:
        raise SystemExit("rejected mutation performed a cached read")

    response = http.patch(
        "/products/shared?tenant_id=south",
        json={"description": revision},
        headers={"X-Demo-Principal": "alice"},
    )
    updated = Product(product_id="shared", description=revision, rank=2)
    if (
        response.status_code != 200
        or Product.model_validate_json(response.text) != updated
    ):
        raise SystemExit("direct write-response read did not observe the update")
    if recorded_outcome(reads_before, manager.snapshot()) != "direct":
        raise SystemExit("write-response read used the cache")

    started = monotonic()
    updated_page = (
        updated,
        Product(product_id="last", description="north last", rank=3),
    )
    while True:
        item, item_outcome = outcome_of(manager, partial(checked_item, http, "alice"))
        page, page_outcome = outcome_of(manager, partial(checked_page, http, "alice"))
        elapsed = monotonic() - started
        if (
            item == updated
            and page == updated_page
            and item_outcome == page_outcome == warm
            and elapsed < 5
        ):
            break
        if elapsed >= 5:
            message = (
                f"updated catalogue item and page were not {warm} reads "
                "within five seconds"
            )
            raise SystemExit(message)
        sleep(0.05)
    if checked_item(http, "bob").description != "south shared":
        raise SystemExit("mutation changed the other tenant's product")
    print(f"update observed after: {(monotonic() - started) * 1000:.0f} ms")

    if content_cache_enabled:
        before = manager.snapshot()  # pytriage: TR11 - Capture first.
        if portal.call(session_bound_read, repository) != updated:
            raise SystemExit(
                "session-bound cached-view read returned unexpected content"
            )
        after = manager.snapshot()
        if (
            recorded_outcome(before, after) != "bypass"
            or session_bypasses(after) - session_bypasses(before) != 1
        ):
            raise SystemExit("session-bound cached-view read did not bypass")
        if after.entry_count == 0:
            raise SystemExit("no catalogue entries admitted before shutdown")
    elif (
        manager.snapshot() != deployment_start
        or manager.stream_health_snapshot(DATABASE_NAME).status
        is not StreamHealthStatus.NOT_STARTED
    ):
        raise SystemExit("direct deployment recorded cache activity")
    report(f"{'cached' if content_cache_enabled else 'direct'} deployment", manager)


@asynccontextmanager
async def checked_lifespan(app: FastAPI) -> AsyncGenerator[None]:
    async with lifespan(app):
        yield
    repository = cast("CatalogueRepository", app.state.repository)
    snapshot = repository.manager.snapshot()
    if (
        snapshot.lifecycle != "closed"
        or snapshot.entry_count != 0
        or snapshot.used_bytes != 0
        or repository.manager.stream_health_snapshot(DATABASE_NAME).status
        is not StreamHealthStatus.CLOSED
    ):
        raise SystemExit("lifespan did not complete manager cleanup")
    try:
        await repository.manager.client.admin.command("ping")
    except InvalidOperation:
        report("lifespan closed manager and client", repository.manager)
    else:
        raise SystemExit("lifespan did not close the MongoDB client")


def main() -> None:
    north_description = "north shared"
    for phase, (content_cache_enabled, revision) in enumerate(DEPLOYMENTS):
        app = create_app(content_cache_enabled=content_cache_enabled)
        app.router.lifespan_context = checked_lifespan
        with TestClient(app) as http:
            if (
                http.get(
                    "/products/shared", headers={"X-Demo-Principal": "alice"}
                ).status_code
                != 401
            ):
                raise SystemExit(
                    "application accepted identity without trusted dependency"
                )
            app.dependency_overrides[authenticated_principal] = demonstration_principal
            repository = cast("CatalogueRepository", app.state.repository)
            portal = cast("BlockingPortal", http.portal)
            completed = False
            try:
                if phase == 0:
                    portal.call(seed_catalogue, repository)
                run_scenario(
                    http,
                    repository,
                    portal,
                    content_cache_enabled=content_cache_enabled,
                    north_description=north_description,
                    revision=revision,
                )
                completed = True
            finally:
                if not completed or phase == len(DEPLOYMENTS) - 1:
                    portal.call(repository.manager.client.drop_database, DATABASE_NAME)
        north_description = revision


if __name__ == "__main__":
    main()
