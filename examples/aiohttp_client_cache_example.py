# /// script
# requires-python = ">=3.14.6"
# dependencies = ["client-query-cache", "aiohttp-client-cache[mongodb]>=0.15.0"]
#
# [tool.uv.sources]
# client-query-cache = { path = "..", editable = true }
# ///

import asyncio
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from time import monotonic
from typing import TYPE_CHECKING, Any

from aiohttp import web
from aiohttp_client_cache.backends.base import CacheBackend, ResponseOrKey
from aiohttp_client_cache.backends.mongodb import (
    MongoDBBackend,
    MongoDBCache,
    MongoDBPickleCache,
)
from aiohttp_client_cache.session import CachedSession
from pymongo import AsyncMongoClient

from client_query_cache.asynchronous import CacheManager

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

DATABASE_NAME = "client_query_cache_example_aiohttp_client_cache"
DEFAULT_MONGODB_URI = "mongodb://localhost:27017/?directConnection=true"


class CachedMongoDBCache(MongoDBCache):
    def __init__(
        self, manager: CacheManager[dict[str, Any]], collection_name: str
    ) -> None:
        super().__init__(DATABASE_NAME, collection_name, connection=manager.client)
        self.cached_collection = manager.get_cached_collection(self.collection)

    async def read(self, key: str) -> ResponseOrKey:
        document = await self.cached_collection.find_one(
            {"_id": key}, projection={"_id": False, "data": True}
        )
        return None if document is None else document["data"]

    async def contains(self, key: str) -> bool:
        return bool(
            await self.cached_collection.find_one(
                {"_id": key}, projection={"_id": True}
            )
        )


class CachedMongoDBPickleCache(MongoDBPickleCache, CachedMongoDBCache):
    pass


class CachedMongoDBBackend(MongoDBBackend):
    def __init__(self, manager: CacheManager[dict[str, Any]]) -> None:
        CacheBackend.__init__(self, cache_name=DATABASE_NAME, autoclose=True)
        self.responses = CachedMongoDBPickleCache(manager, "responses")
        self.redirects = CachedMongoDBCache(manager, "redirects")


@dataclass(slots=True)
class Origin:
    url: str
    hits: int = 0


@asynccontextmanager
async def local_origin() -> AsyncGenerator[Origin]:
    origin = Origin("")

    async def item(_request: web.Request) -> web.Response:  # noqa: RUF029 -- aiohttp handler contract
        origin.hits += 1
        return web.json_response({"origin_hit": origin.hits})

    app = web.Application()
    app.router.add_get("/item", item)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        host, port = runner.addresses[0]
        origin.url = f"http://{host}:{port}/item"
        yield origin
    finally:
        await runner.cleanup()


async def request_item(session: CachedSession, origin: Origin) -> None:
    async with session.get(origin.url) as response:
        if response.status != 200:
            raise SystemExit("local origin request failed")
        payload = await response.json()
        if payload["origin_hit"] != origin.hits:
            raise SystemExit("response did not match the current origin hit count")


async def run_scenario(
    session: CachedSession, origin: Origin, manager: CacheManager[dict[str, Any]]
) -> None:
    await request_item(session, origin)
    hits_before = manager.snapshot().hits
    for _ in range(5):
        await request_item(session, origin)
    if manager.snapshot().hits - hits_before < 4:
        raise SystemExit("no cache hits for repeated storage reads")
    if origin.hits != 1:
        raise SystemExit("repeated requests did not use the stored response")

    await session.delete_url(origin.url)
    started = monotonic()
    while await session.cache.has_url(origin.url):
        if monotonic() - started >= 5:
            raise SystemExit("invalidation not observed for the deleted response")
        await asyncio.sleep(0.05)
    print(f"invalidation observed after: {(monotonic() - started) * 1000:.0f} ms")
    await request_item(session, origin)
    if origin.hits != 2:
        raise SystemExit("deleted response was not fetched from the origin again")
    snapshot = manager.snapshot()
    print(f"origin hits: {origin.hits}")
    print(
        f"cache hits: {snapshot.hits}, misses: {snapshot.misses}, "
        f"bypasses: {snapshot.bypasses}"
    )


async def main() -> None:
    mongodb_uri = os.getenv("MONGODB_URI", DEFAULT_MONGODB_URI)
    async with AsyncMongoClient[dict[str, Any]](mongodb_uri) as client:
        await client.drop_database(DATABASE_NAME)
        async with (
            CacheManager(client) as manager,
            local_origin() as origin,
            CachedSession(cache=CachedMongoDBBackend(manager)) as session,
        ):
            await run_scenario(session, origin, manager)


if __name__ == "__main__":
    asyncio.run(main())
