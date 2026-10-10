# ruff: noqa: INP001 - ASGI application for the research launch smoke.
from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

from pymongo import AsyncMongoClient

from benchmarks.stream_cost.shared_cache.adapters import AsyncSharedCacheManager
from benchmarks.stream_cost.shared_cache.attachment import AsyncEndpoint
from research.shared_cache_launch.launch_owner import attachment_from_environment

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

_state: dict[str, AsyncSharedCacheManager[dict[str, Any]]] = {}


async def _manager() -> AsyncSharedCacheManager[dict[str, Any]]:
    try:
        return _state["manager"]
    except KeyError:
        client = AsyncMongoClient[dict[str, Any]](
            os.environ["SHARED_CACHE_MONGODB_URI"], directConnection=True
        )
        endpoint = await AsyncEndpoint.attach(attachment_from_environment())
        manager = AsyncSharedCacheManager(client, endpoint)
        _state["manager"] = manager
        return manager


async def app(
    scope: dict[str, Any],
    _receive: Callable[[], Awaitable[dict[str, Any]]],
    send: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    if scope["type"] != "http":
        return
    manager = await _manager()
    key = int(scope["path"].strip("/"))
    collection = manager[os.environ["SHARED_CACHE_DATABASE"]]["catalogue"]
    document = await collection.find_one({"_id": key})
    body = json.dumps(
        {
            "pid": os.getpid(),
            "id": None if document is None else document["_id"],
            "hits": manager.observation.hits,
            "misses": manager.observation.misses,
            "bypasses": manager.observation.bypasses,
            "incarnation": str(manager.endpoint.incarnation),
        }
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": body})
