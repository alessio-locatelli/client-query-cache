import asyncio
import importlib

from pymongo import AsyncMongoClient, MongoClient

from client_query_cache import SharedCacheConfig, SharedCacheManager, SharedCacheServer
from client_query_cache.asynchronous import (
    SharedCacheManager as AsyncSharedCacheManager,
)

for module_name in (
    "client_query_cache",
    "client_query_cache.synchronous",
    "client_query_cache.asynchronous",
):
    module = importlib.import_module(module_name)
    for name in module.__all__:
        getattr(module, name)


async def verify_async(server: SharedCacheServer) -> None:
    async with (
        AsyncMongoClient("mongodb://127.0.0.1:1", connect=False) as client,
        AsyncSharedCacheManager(client, server.connection),
    ):
        pass


if __name__ == "__main__":
    with SharedCacheServer(
        "mongodb://127.0.0.1:1",
        ("artifact_check",),
        config=SharedCacheConfig(
            budget_bytes=65_536,
            max_entry_bytes=4096,
            slots=64,
            arena_bytes=131_072,
            namespaces=4,
            connections=8,
        ),
        client_options={"connect": False},
    ) as server:
        with (
            MongoClient("mongodb://127.0.0.1:1", connect=False) as client,
            SharedCacheManager(client, server.connection),
        ):
            pass
        asyncio.run(verify_async(server))
        server.restart()
