# /// script
# requires-python = ">=3.14"
# dependencies = ["client-query-cache", "cachier[mongo]>=4.2.0"]
#
# [tool.uv.sources]
# client-query-cache = { path = "..", editable = true }
# ///

import asyncio
import os
from time import monotonic
from typing import Any

from cachier import cachier
from pymongo import AsyncMongoClient

from client_query_cache import CacheCoreConfig
from client_query_cache._types import NonNegativeInt
from client_query_cache.asynchronous import CacheManager

DATABASE_NAME = "client_query_cache_example_cachier_async"
DEFAULT_MONGODB_URI = "mongodb://localhost:27017/?directConnection=true"
WAIT_TIMEOUT_SECONDS = 10.0


class CachedCollection:
    """Cache storage reads and retain PyMongo's write and index operations."""

    def __init__(self, manager: CacheManager[dict[str, Any]]) -> None:
        collection = manager.client[DATABASE_NAME]["function_results"]
        self.cached_collection = manager.get_cached_collection(collection)
        self.find_one = self.cached_collection.find_one
        self.update_one = collection.update_one
        self.update_many = collection.update_many
        self.delete_many = collection.delete_many
        self.index_information = collection.index_information
        self.create_indexes = collection.create_indexes


async def run_scenario(manager: CacheManager[dict[str, Any]]) -> None:
    orders = manager.client[DATABASE_NAME]["orders"]
    await orders.insert_many(
        (
            {"_id": "order-1", "region": "North", "amount_eur": 120},
            {"_id": "order-2", "region": "North", "amount_eur": 80},
            {"_id": "order-3", "region": "South", "amount_eur": 50},
        )
    )
    adapter = CachedCollection(manager)

    async def mongetter() -> CachedCollection:  # noqa: RUF029 -- cachier requires an async mongetter
        return adapter

    calculations: NonNegativeInt = 0

    # cachier's decorator has no return annotation and types mongetter as a
    # concrete Collection. This adapter supplies the required collection methods.
    @cachier(backend="mongo", mongetter=mongetter)  # type: ignore[arg-type, untyped-decorator]
    async def report(region: str) -> NonNegativeInt:
        nonlocal calculations
        calculations += 1
        cursor = await orders.aggregate(
            [
                {"$match": {"region": region}},
                {"$group": {"_id": None, "sales_eur": {"$sum": "$amount_eur"}}},
            ]
        )
        totals = await cursor.to_list()
        return totals[0]["sales_eur"] if totals else 0

    if await report("North") != 200:
        raise SystemExit("initial North sales report should total EUR 200")
    print("initial North sales: EUR 200")

    # Wait for storage writes to settle and for repeated lookups to hit the cache.
    hits_before = manager.snapshot().hits
    started = monotonic()
    while True:
        for _ in range(5):
            if await report("North") != 200 or calculations != 1:
                raise SystemExit("repeated calls must reuse one EUR 200 calculation")
        cache_hits = manager.snapshot().hits - hits_before
        if cache_hits > 0:
            break
        if monotonic() - started >= WAIT_TIMEOUT_SECONDS:
            raise SystemExit("cache warm-up timed out: no query-cache hits")
        await asyncio.sleep(0.05)
    print(f"repeated calls: {calculations} calculation, {cache_hits} query-cache hits")

    await orders.update_one({"_id": "order-2"}, {"$set": {"amount_eur": 100}})
    if await report("North") != 200 or calculations != 1:
        raise SystemExit("changing orders alone should preserve the stored report")

    await report.aclear_cache()
    started = monotonic()
    while await report("North") != 220:
        if monotonic() - started >= WAIT_TIMEOUT_SECONDS:
            raise SystemExit("invalidation timed out: cleared report is still stale")
        await asyncio.sleep(0.05)
    if calculations != 2:
        raise SystemExit("clearing should cause exactly one new calculation")
    print("updated North sales: EUR 220; calculations: 2")
    print(f"invalidation observed after: {(monotonic() - started) * 1000:.0f} ms")


async def main() -> None:
    mongodb_uri = os.getenv("MONGODB_URI", DEFAULT_MONGODB_URI)
    async with AsyncMongoClient[dict[str, Any]](mongodb_uri) as client:
        await client.drop_database(DATABASE_NAME)
        await client[DATABASE_NAME].create_collection("function_results")
        async with CacheManager(
            client, cache_config=CacheCoreConfig(enable_telemetry=True)
        ) as manager:
            await run_scenario(manager)


if __name__ == "__main__":
    asyncio.run(main())
