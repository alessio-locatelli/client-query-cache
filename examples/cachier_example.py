# /// script
# requires-python = ">=3.14"
# dependencies = ["client-query-cache", "cachier[mongo]>=4.2.0"]
#
# [tool.uv.sources]
# client-query-cache = { path = "..", editable = true }
# ///

import os
from time import monotonic, sleep
from typing import Any

from cachier import cachier
from pymongo import MongoClient

from client_query_cache import CacheCoreConfig, CacheManager
from client_query_cache._types import NonNegativeInt

DATABASE_NAME = "client_query_cache_example_cachier"
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


def run_scenario(manager: CacheManager[dict[str, Any]]) -> None:
    orders = manager.client[DATABASE_NAME]["orders"]
    orders.insert_many(
        (
            {"_id": "order-1", "region": "North", "amount_eur": 120},
            {"_id": "order-2", "region": "North", "amount_eur": 80},
            {"_id": "order-3", "region": "South", "amount_eur": 50},
        )
    )
    adapter = CachedCollection(manager)

    def mongetter() -> CachedCollection:
        return adapter

    calculations: NonNegativeInt = 0

    # cachier's decorator has no return annotation and types mongetter as a
    # concrete Collection. This adapter supplies the required collection methods.
    @cachier(backend="mongo", mongetter=mongetter)  # type: ignore[arg-type, untyped-decorator]
    def report(region: str) -> NonNegativeInt:
        nonlocal calculations
        calculations += 1
        totals = tuple(
            orders.aggregate(
                [
                    {"$match": {"region": region}},
                    {"$group": {"_id": None, "sales_eur": {"$sum": "$amount_eur"}}},
                ]
            )
        )
        return totals[0]["sales_eur"] if totals else 0

    if report("North") != 200:
        raise SystemExit("initial North sales report should total EUR 200")
    print("initial North sales: EUR 200")

    # Wait for storage writes to settle and for repeated lookups to hit the cache.
    hits_before = manager.snapshot().hits
    started = monotonic()
    while True:
        for _ in range(5):
            if report("North") != 200 or calculations != 1:
                raise SystemExit("repeated calls must reuse one EUR 200 calculation")
        cache_hits = manager.snapshot().hits - hits_before
        if cache_hits > 0:
            break
        if monotonic() - started >= WAIT_TIMEOUT_SECONDS:
            raise SystemExit("cache warm-up timed out: no query-cache hits")
        sleep(0.05)
    print(f"repeated calls: {calculations} calculation, {cache_hits} query-cache hits")

    orders.update_one({"_id": "order-2"}, {"$set": {"amount_eur": 100}})
    if report("North") != 200 or calculations != 1:
        raise SystemExit("changing orders alone should preserve the stored report")

    report.clear_cache()
    started = monotonic()
    while report("North") != 220:
        if monotonic() - started >= WAIT_TIMEOUT_SECONDS:
            raise SystemExit("invalidation timed out: cleared report is still stale")
        sleep(0.05)
    if calculations != 2:
        raise SystemExit("clearing should cause exactly one new calculation")
    print("updated North sales: EUR 220; calculations: 2")
    print(f"invalidation observed after: {(monotonic() - started) * 1000:.0f} ms")


def main() -> None:
    mongodb_uri = os.getenv("MONGODB_URI", DEFAULT_MONGODB_URI)
    with MongoClient[dict[str, Any]](mongodb_uri) as client:
        client.drop_database(DATABASE_NAME)
        client[DATABASE_NAME].create_collection("function_results")
        with CacheManager(
            client, cache_config=CacheCoreConfig(enable_telemetry=True)
        ) as manager:
            run_scenario(manager)


if __name__ == "__main__":
    main()
