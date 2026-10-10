# ruff: noqa: INP001 - WSGI application for the research launch smoke.
from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

from pymongo import MongoClient

from benchmarks.stream_cost.shared_cache.adapters import SharedCacheManager
from benchmarks.stream_cost.shared_cache.attachment import SyncEndpoint
from research.shared_cache_launch.launch_owner import attachment_from_environment

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

_state: dict[str, SharedCacheManager[dict[str, Any]]] = {}


def _manager() -> SharedCacheManager[dict[str, Any]]:
    try:
        return _state["manager"]
    except KeyError:
        client = MongoClient[dict[str, Any]](
            os.environ["SHARED_CACHE_MONGODB_URI"], directConnection=True
        )
        manager = SharedCacheManager(
            client, SyncEndpoint(attachment_from_environment())
        )
        _state["manager"] = manager
        return manager


def application(
    environ: dict[str, Any],
    start_response: Callable[[str, list[tuple[str, str]]], object],
) -> Iterable[bytes]:
    manager = _manager()
    key = int(environ["PATH_INFO"].strip("/"))
    collection = manager[os.environ["SHARED_CACHE_DATABASE"]]["catalogue"]
    document = collection.find_one({"_id": key})
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
    start_response("200 OK", [("Content-Type", "application/json")])
    return [body]
