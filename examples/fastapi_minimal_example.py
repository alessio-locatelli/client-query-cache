# /// script
# requires-python = ">=3.14"
# dependencies = ["client-query-cache", "fastapi>=0.143.0", "httpx2>=2.13.1"]
#
# [tool.uv.sources]
# client-query-cache = { path = "..", editable = true }
# ///

# --8<-- [start:imports]
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import partial
from time import monotonic, sleep
from typing import TYPE_CHECKING, Annotated, TypedDict

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field
from pymongo import AsyncMongoClient, MongoClient, ReadPreference
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from client_query_cache.asynchronous import (
    BypassReason,
    CacheCoreConfig,
    CacheManager,
    CacheSnapshot,
    StreamHealthStatus,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable

    from pymongo.asynchronous.collection import AsyncCollection

    from client_query_cache.asynchronous import CachedCollection

# --8<-- [end:imports]
# --8<-- [start:application]
DATABASE_NAME = "client_query_cache_example_fastapi_minimal"
MONGODB_URI = os.getenv(
    "MONGODB_URI", "mongodb://localhost:27017/?directConnection=true"
)
NonEmptyStr = Annotated[str, Field(min_length=1)]


class ProductDocument(TypedDict):
    _id: NonEmptyStr
    description: NonEmptyStr


class DescriptionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: Annotated[str, Field(min_length=1, max_length=200)]


@dataclass
class Resources:
    client: AsyncMongoClient[ProductDocument]
    manager: CacheManager[ProductDocument]
    raw: AsyncCollection[ProductDocument]
    cached: CachedCollection[ProductDocument]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    async with (
        AsyncMongoClient[ProductDocument](MONGODB_URI) as client,
        CacheManager(
            client, cache_config=CacheCoreConfig(max_entry_bytes=1024)
        ) as manager,
    ):
        raw = client[DATABASE_NAME].get_collection(
            "products",
            read_preference=ReadPreference.PRIMARY,
            read_concern=ReadConcern("majority"),
            write_concern=WriteConcern(w="majority"),
        )
        app.state.resources = Resources(
            client, manager, raw, manager.get_cached_collection(raw)
        )
        yield


app = FastAPI(lifespan=lifespan)


def resources(request: Request) -> Resources:
    owned: Resources = request.app.state.resources
    return owned


@app.get("/products/{product_id}")
async def read_product(product_id: NonEmptyStr, request: Request) -> ProductDocument:
    product = await resources(request).cached.find_one({"_id": product_id})
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@app.patch("/products/{product_id}")
async def update_product(
    product_id: NonEmptyStr,
    update: DescriptionUpdate,
    request: Request,
) -> ProductDocument:
    owned = resources(request)
    async with owned.client.start_session(causal_consistency=True) as session:
        await owned.raw.update_one(
            {"_id": product_id},
            {"$set": {"description": update.description}},
            session=session,
        )
        product = await owned.raw.find_one({"_id": product_id}, session=session)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@app.get("/metrics/cache")
def cache_metrics(request: Request) -> CacheSnapshot:
    return resources(request).manager.snapshot()


# --8<-- [end:application]


def require(*, condition: bool, message: NonEmptyStr) -> None:
    if not condition:
        raise SystemExit(message)


def check_reason(
    before: CacheSnapshot, after: CacheSnapshot, reason: BypassReason
) -> None:
    changes = {
        latest.reason: latest.count - previous.count
        for previous, latest in zip(
            before.bypass_reasons, after.bypass_reasons, strict=True
        )
    }
    require(
        condition=changes[reason] == 1 and after.bypasses - before.bypasses == 1,
        message=f"missing {reason} bypass",
    )
    require(
        condition=after.hits == before.hits and after.misses == before.misses,
        message=f"{reason} bypass recorded a cache lookup",
    )
    print(f"{reason}: bypasses +1, reason +1, hits/misses unchanged")


async def observed_bypass(
    owned: Resources,
    reason: BypassReason,
    read: Callable[[], Awaitable[object]],
) -> None:
    before = owned.manager.snapshot()
    delivered = await read()
    require(
        condition=bool(delivered), message=f"{reason} bypass did not deliver a document"
    )
    check_reason(before, owned.manager.snapshot(), reason)


async def check_eligibility(owned: Resources) -> None:
    # --8<-- [start:session]
    async with owned.client.start_session() as session:
        read = partial(owned.cached.find_one, {"_id": "book"}, session=session)
        await observed_bypass(owned, BypassReason.SESSION, read)
    # --8<-- [end:session]
    # --8<-- [start:cursor]
    cursor = owned.cached.find({"_id": "book"}, allow_partial_results=True)
    await observed_bypass(owned, BypassReason.UNSUPPORTED_OPTIONS, cursor.to_list)
    # --8<-- [end:cursor]
    # --8<-- [start:pipeline]
    await observed_bypass(
        owned,
        BypassReason.UNSAFE_PIPELINE,
        partial(sampled_product, owned),
    )
    # --8<-- [end:pipeline]
    # --8<-- [start:oversized]
    before = owned.manager.snapshot()
    large = await owned.cached.find_one({"_id": "large"})
    after = owned.manager.snapshot()
    require(
        condition=large is not None and len(large["description"]) == 2048,
        message="oversized read did not deliver the complete document",
    )
    require(
        condition=after.oversized_bypasses - before.oversized_bypasses == 1
        and after.misses - before.misses == 1
        and after.bypasses == before.bypasses,
        message="oversized read did not record a miss and separate oversized bypass",
    )
    print("oversized: misses +1, oversized_bypasses +1, ordinary bypasses unchanged")
    # --8<-- [end:oversized]


async def sampled_product(owned: Resources) -> list[ProductDocument]:
    # --8<-- [start:sample]
    pipeline: list[dict[NonEmptyStr, object]] = [
        {"$match": {"_id": "book"}},
        {"$sample": {"size": 1}},
    ]
    return await (await owned.cached.aggregate(pipeline)).to_list()
    # --8<-- [end:sample]


def check_application(http: TestClient, owned: Resources) -> None:
    deadline = monotonic() + 5
    while (
        owned.manager.stream_health_snapshot(DATABASE_NAME).status
        is not StreamHealthStatus.HEALTHY
    ):
        require(
            condition=monotonic() < deadline,
            message="stream did not become healthy within five seconds",
        )
        require(
            condition=http.get("/products/readiness").status_code == 404,
            message="missing read did not return 404",
        )
        sleep(0.01)

    # --8<-- [start:reuse]
    before = owned.manager.snapshot()
    first = http.get("/products/book")
    missed = owned.manager.snapshot()
    second = http.get("/products/book")
    hit = owned.manager.snapshot()
    require(
        condition=first.status_code == second.status_code == 200
        and first.json() == second.json(),
        message="repeated endpoint reads disagree",
    )
    require(
        condition=missed.misses - before.misses == 1 and hit.hits - missed.hits == 1,
        message="missing endpoint miss followed by hit",
    )
    print("repeated endpoint: misses +1, then hits +1")
    # --8<-- [end:reuse]

    before_write = owned.manager.snapshot()
    invalidations_before = owned.manager.stream_cost_snapshot(
        DATABASE_NAME
    ).invalidations
    updated = http.patch("/products/book", json={"description": "updated description"})
    expected = {"_id": "book", "description": "updated description"}
    require(
        condition=updated.status_code == 200 and updated.json() == expected,
        message="direct write response did not observe the update",
    )
    after_write = owned.manager.snapshot()
    require(
        condition=(after_write.hits, after_write.misses, after_write.bypasses)
        == (before_write.hits, before_write.misses, before_write.bypasses),
        message="direct write response changed cache outcome counters",
    )
    print("write acknowledged; direct response contains updated description")
    started = monotonic()
    while True:
        before_read = owned.manager.snapshot()
        response = http.get("/products/book")
        after_read = owned.manager.snapshot()
        require(condition=response.status_code == 200, message="post-write read failed")
        delivered = response.json()
        print(f"cached endpoint after write: {delivered['description']}")
        if delivered == expected and after_read.hits > before_read.hits:
            break
        require(
            condition=monotonic() - started < 5,
            message="updated cache hit absent after five seconds",
        )
        sleep(0.01)
    print(f"updated cache hit observed after {(monotonic() - started) * 1000:.0f} ms")
    require(
        condition=owned.manager.stream_cost_snapshot(DATABASE_NAME).invalidations
        > invalidations_before,
        message="updated cache hit was observed without a stream invalidation",
    )
    print(
        "stream invalidation observed; later cached read contains updated description"
    )
    snapshot = owned.manager.snapshot()
    require(
        condition=http.get("/metrics/cache").json()["hits"] == snapshot.hits,
        message="metrics endpoint did not expose the public snapshot",
    )
    require(
        condition=http.patch(
            "/products/missing", json={"description": "unused"}
        ).status_code
        == 404,
        message="missing update did not return 404",
    )


def main() -> None:
    with MongoClient[ProductDocument](MONGODB_URI) as setup:
        setup.drop_database(DATABASE_NAME)
        collection = setup[DATABASE_NAME].get_collection(
            "products", write_concern=WriteConcern(w="majority")
        )
        collection.insert_many(
            (
                {"_id": "book", "description": "original description"},
                {"_id": "large", "description": "x" * 2048},
            )
        )
        try:
            with TestClient(app) as http:
                owned: Resources = app.state.resources
                check_application(http, owned)
                assert http.portal is not None
                http.portal.call(check_eligibility, owned)
            closed = owned.manager.snapshot()
            require(
                condition=closed.entry_count == closed.used_bytes == 0
                and closed.lifecycle == "closed",
                message="manager did not release cache resources on shutdown",
            )
            print("shutdown: manager closed and cache released before client closure")
        finally:
            setup.drop_database(DATABASE_NAME)


if __name__ == "__main__":
    main()
