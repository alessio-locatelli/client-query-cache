# ruff: noqa: PLC2701, SLF001 - Compare the internal adapters and native publication directly.
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
import types
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, cast

from pymongo import AsyncMongoClient, MongoClient

from client_query_cache._core.collection_metadata import CollectionMetadata
from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.manager import CacheCore, CacheCoreConfig
from client_query_cache._shared import adapters
from client_query_cache._shared.shared_index import ArenaPayloads, IndexPublisher
from client_query_cache._shared_index import OwnerIndex, ReaderIndex
from client_query_cache._types import BsonDict, JsonDict, PositiveInt

type Model = Literal["sync", "async"]
type View = (
    adapters.SharedCachedCollection[BsonDict]
    | adapters.AsyncSharedCachedCollection[BsonDict]
)


class Endpoint:
    __slots__ = ()

    config = SimpleNamespace(max_entry_bytes=1024 * 1024, max_namespaces=1)
    incarnation = 1
    connected = True

    def _check_owner(self) -> None:
        pass


def _view(
    module: types.ModuleType,
    client: MongoClient[BsonDict] | AsyncMongoClient[BsonDict],
    model: Model,
) -> View:
    cls = (
        module.SharedCacheManager if model == "sync" else module.AsyncSharedCacheManager
    )
    manager = cls(client, Endpoint(), local)
    manager._metadata.store(
        namespace,
        CollectionMetadata(checked_epoch=0, bypass_reason=None, default_collation=None),
    )
    manager._slots.store(namespace, (0, 0, 1))
    collection = manager[namespace.database][namespace.collection]
    core.admit_identity(
        core.begin_identity_admission(namespace, 7),
        collection._find_one_default_shape,
        {"_id": 7, "payload": "x" * 4096},
    )
    return cast("View", collection)


async def _batch(collection: View, model: Model, hits: PositiveInt) -> JsonDict:
    ring.drain()
    publisher.progress(namespace.database)
    dropped = ring.dropped()  # pytriage: TR11 - Snapshot before timing.
    start, wall = time.thread_time_ns(), time.perf_counter_ns()
    if model == "sync":
        for _ in range(hits):
            collection.find_one({"_id": 7})
    else:
        for _ in range(hits):
            await collection.find_one({"_id": 7})
    timing = {
        "cpu_us": (time.thread_time_ns() - start) / hits / 1000,
        "wall_us": (time.perf_counter_ns() - wall) / hits / 1000,
    }
    assert ring.dropped() == dropped
    return timing


async def run(*, same_view: bool) -> None:
    rows: list[JsonDict] = []
    helpers = {"main": baseline._local_select, "candidate": adapters._local_select}
    for model in ("sync", "async"):
        client = (
            MongoClient(connect=False)
            if model == "sync"
            else AsyncMongoClient(connect=False)
        )
        views = {
            "main": _view(baseline, client, model),
            "candidate": _view(adapters, client, model),
        }
        if same_view:
            views["main"] = views["candidate"]
        for name, collection in views.items():
            if same_view:
                adapters._local_select = helpers[name]
            before = collection._shared.observation.hits
            await _batch(collection, model, 10000)
            assert collection._shared.observation.hits == before + 10000
        for repetition in range(10):
            names = (
                ("main", "candidate") if repetition % 2 == 0 else ("candidate", "main")
            )
            for name in names:
                if same_view:
                    adapters._local_select = helpers[name]
                rows.append(
                    {
                        "model": model,
                        "source": name,
                        "repetition": repetition,
                        **await _batch(views[name], model, 20000),
                    }
                )
        if model == "sync":
            client.close()
        else:
            await client.close()
    print(
        json.dumps(
            {
                "baseline_revision": BASE,
                "candidate_adapter_sha256": CANDIDATE_ADAPTER_SHA256,
                "comparison": "helpers" if same_view else "adapters",
                "batches": rows,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    # Pinned public Git revision.
    BASE = "5af2d8b210a42ef2619fb2a4e895e36c6fb7d243"  # pragma: allowlist secret
    CANDIDATE_ADAPTER_SHA256 = sha256(Path(adapters.__file__).read_bytes()).hexdigest()
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is required to load the pinned comparison source")
    source = subprocess.check_output(  # noqa: S603 - Fixed arguments load a pinned revision from this repository.
        [git, "show", BASE + ":src/client_query_cache/_shared/adapters.py"]
    )
    baseline = types.ModuleType("client_query_cache._shared.main_adapters")
    sys.modules[baseline.__name__] = baseline
    exec(compile(source, "main_adapters.py", "exec"), baseline.__dict__)  # noqa: S102 - Execute only the pinned local repository source above.
    namespace = NamespaceId("diagnostic", "hot")
    index = OwnerIndex(1024, 4 * 1024 * 1024, 1, 1, 1, 60 * 10**9)
    publisher = IndexPublisher(index, (namespace.database,), 1)
    core = CacheCore(
        CacheCoreConfig(), observer=publisher, payloads=ArenaPayloads(index)
    )
    publisher.assign(namespace, core.current_epoch(namespace))
    ring = index.session_ring(65536)
    fd = index.reader_descriptor()
    reader = ReaderIndex(fd, ring.descriptor())
    ring.close_descriptor()
    local = SimpleNamespace(reader=reader, incarnation=1, admissions_enabled=True)
    parser = argparse.ArgumentParser(
        description="Compare warmed identity reads against a pinned baseline."
    )
    parser.add_argument(
        "--same-view",
        action="store_true",
        help="Use one collection view for both selection helpers.",
    )
    arguments = parser.parse_args()
    try:
        asyncio.run(run(same_view=arguments.same_view))
    finally:
        core.close()
        os.close(fd)
