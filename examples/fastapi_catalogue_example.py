# /// script
# requires-python = ">=3.14"
# dependencies = ["client-query-cache", "fastapi>=0.143.0", "httpx2>=2.13.1"]
#
# [tool.uv.sources]
# client-query-cache = { path = "..", editable = true }
# ///

import os
from contextlib import asynccontextmanager
from time import monotonic, sleep
from typing import TYPE_CHECKING, Annotated, Literal, TypedDict, cast

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.testclient import TestClient
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveInt,
    TypeAdapter,
)
from pymongo import AsyncMongoClient
from pymongo.errors import InvalidOperation
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from client_query_cache.asynchronous import CacheManager

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from anyio.from_thread import BlockingPortal

DATABASE_NAME = "client_query_cache_example_fastapi_catalogue"
DEFAULT_MONGODB_URI = "mongodb://localhost:27017/?directConnection=true"
PAGE_URL = "/products?offset=1&page_size=2"
NonEmptyStr = Annotated[str, Field(min_length=1)]
TenantId = Literal["north", "south"]


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
    def __init__(self, manager: CacheManager[ProductDocument]) -> None:
        self.manager = manager
        self.raw = manager.client[DATABASE_NAME].get_collection(
            "products",
            read_concern=ReadConcern("majority"),
            write_concern=WriteConcern(w="majority"),
        )
        self.cached = manager.get_cached_collection(self.raw)

    async def describe(self, tenant_id: TenantId, product_id: NonEmptyStr) -> Product:
        document = await self.cached.find_one(
            {"tenant_id": tenant_id, "product_id": product_id}
        )
        if document is None:
            raise HTTPException(status_code=404, detail="Product not found")
        return Product.model_validate(document)

    async def page(
        self, tenant_id: TenantId, offset: NonNegativeInt, page_size: PositiveInt
    ) -> tuple[Product, ...]:
        documents = await (
            self.cached.find({"tenant_id": tenant_id})
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
        app.state.repository = CatalogueRepository(manager)
        yield


def authenticated_principal() -> Principal:
    raise HTTPException(status_code=401, detail="Trusted authentication required")


def catalogue_repository(request: Request) -> CatalogueRepository:
    return cast("CatalogueRepository", request.app.state.repository)


app = FastAPI(lifespan=lifespan)
TrustedPrincipal = Annotated[Principal, Depends(authenticated_principal)]
Repository = Annotated[CatalogueRepository, Depends(catalogue_repository)]


@app.get("/products/{product_id}")
async def describe_product(
    product_id: NonEmptyStr, principal: TrustedPrincipal, repository: Repository
) -> Product:
    return await repository.describe(principal.tenant_id, product_id)


@app.get("/products")
async def product_page(
    principal: TrustedPrincipal,
    repository: Repository,
    offset: Annotated[int, Query(ge=0)] = 0,
    page_size: Annotated[int, Query(ge=1, le=50)] = 10,
) -> tuple[Product, ...]:
    return await repository.page(principal.tenant_id, offset, page_size)


@app.patch("/products/{product_id}")
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


def run_scenario(http: TestClient, repository: CatalogueRepository) -> None:
    manager = repository.manager
    reads_before = manager.snapshot()  # pytriage: TR11 - Capture first.
    for method in ("GET", "PATCH"):
        response = http.request(
            method, "/products/shared", json={"description": "unauthenticated"}
        )
        if response.status_code != 401:
            raise SystemExit("missing identity was not rejected")
    if manager.snapshot() != reads_before:
        raise SystemExit("unauthenticated request reached cached storage")

    identities: tuple[tuple[Literal["alice", "bob"], TenantId], ...] = (
        ("alice", "north"),
        ("bob", "south"),
    )
    for owner, tenant_id in identities:
        expected = Product(
            product_id="shared", description=f"{tenant_id} shared", rank=2
        )
        expected_page = (
            expected,
            Product(product_id="last", description=f"{tenant_id} last", rank=3),
        )
        for read in (checked_item, checked_page):
            hits_before = manager.snapshot().hits
            for _ in range(5):
                content = read(http, owner)
                if content != (expected if read is checked_item else expected_page):
                    raise SystemExit("item or page tenant isolation failed")
            if manager.snapshot().hits - hits_before < 4:
                message = f"no repeated {read.__name__} cache hits for {owner}"
                raise SystemExit(message)

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
        response = http.get(url, headers={"X-Demo-Principal": "alice"})
        if response.status_code != 200 or "south" in response.text:
            raise SystemExit("client tenant selector replaced authenticated identity")
    reads_before = manager.snapshot()
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
        json={"description": "updated north description"},
        headers={"X-Demo-Principal": "alice"},
    )
    updated = Product(
        product_id="shared", description="updated north description", rank=2
    )
    if (
        response.status_code != 200
        or Product.model_validate_json(response.text) != updated
    ):
        raise SystemExit("direct write-response read did not observe the update")
    reads_after = manager.snapshot()
    if (reads_after.hits, reads_after.misses, reads_after.bypasses) != (
        reads_before.hits,
        reads_before.misses,
        reads_before.bypasses,
    ):
        raise SystemExit("write-response read used the cache")

    started = monotonic()
    updated_page = (
        updated,
        Product(product_id="last", description="north last", rank=3),
    )
    while True:
        hits_before = manager.snapshot().hits
        item = checked_item(http, "alice")
        item_hit = manager.snapshot().hits > hits_before
        hits_before = manager.snapshot().hits
        page = checked_page(http, "alice")
        page_hit = manager.snapshot().hits > hits_before
        elapsed = monotonic() - started
        if (
            item == updated
            and page == updated_page
            and item_hit
            and page_hit
            and elapsed < 5
        ):
            break
        if elapsed >= 5:
            raise SystemExit(
                "updated catalogue item and page were not served from cache "
                "within five seconds"
            )
        sleep(0.05)
    if checked_item(http, "bob").description != "south shared":
        raise SystemExit("mutation changed the other tenant's product")
    snapshot = manager.snapshot()
    if snapshot.entry_count == 0:
        raise SystemExit("no catalogue entries admitted before shutdown")
    print(f"invalidation observed after: {(monotonic() - started) * 1000:.0f} ms")
    print(
        f"cache hits: {snapshot.hits}, misses: {snapshot.misses}, "
        f"bypasses: {snapshot.bypasses}"
    )


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
    ):
        raise SystemExit("lifespan did not complete manager cleanup")
    try:
        await repository.manager.client.admin.command("ping")
    except InvalidOperation:
        print("lifespan closed manager and client")
    else:
        raise SystemExit("lifespan did not close the MongoDB client")


def main() -> None:
    app.router.lifespan_context = checked_lifespan
    try:
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
            try:
                portal.call(seed_catalogue, repository)
                run_scenario(http, repository)
            finally:
                portal.call(repository.manager.client.drop_database, DATABASE_NAME)
    finally:
        app.dependency_overrides.clear()
        app.router.lifespan_context = lifespan


if __name__ == "__main__":
    main()
