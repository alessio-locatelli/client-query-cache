from __future__ import annotations

import argparse
import asyncio
import json
import multiprocessing
import os
import secrets
import statistics
import tempfile
import time
from multiprocessing.managers import BaseManager
from pathlib import Path
from typing import TYPE_CHECKING, cast

import psutil
from bson.codec_options import CodecOptions
from pymongo import MongoClient

from benchmarks.stream_cost.shared_cache.attachment import AsyncEndpoint, SyncEndpoint
from benchmarks.stream_cost.shared_cache.dataset import seed_catalogue
from benchmarks.stream_cost.shared_cache.owner import owner_main
from benchmarks.stream_cost.shared_cache.profiling import PROFILE_DIRECTORY, summarize
from benchmarks.stream_cost.shared_cache.protocol import Registration, comparison_cells
from benchmarks.stream_cost.shared_cache.window import (
    attachment_for,
    owner_config,
    run_window,
)
from benchmarks.stream_cost.shared_cache.wire import encode_key
from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits
from client_query_cache._core.canonical import canonicalize
from client_query_cache._core.codec import codec_fingerprint, decode_value, encode_value
from client_query_cache._core.find_one_reads import find_one_read_shape
from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.manager import CacheCore, CacheCoreConfig

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from multiprocessing.connection import Connection

    from benchmarks.stream_cost.shared_cache.attachment import Message
    from benchmarks.stream_cost.shared_cache.protocol import Cell
    from client_query_cache._types import PositiveInt

type Payload = dict[str, object]

_CONFIG = Path("reports/shared-worker-cache/v2/config.json")
_LABEL = "exploratory diagnostic; excluded from promotion inference"


class _CoarseCache:
    __slots__ = ("_core", "_namespace")

    def __init__(self, entries: int, payload_bytes: int) -> None:
        self._core = CacheCore(CacheCoreConfig(shared_budget_bytes=256 * 1024 * 1024))
        self._namespace = NamespaceId("diagnostic", "catalogue")
        for key in range(entries):
            capture = self._core.begin_identity_admission(self._namespace, key)
            self._core.admit_identity_encoded(
                capture,
                "full",
                encode_value({"_id": key, "payload": "x" * payload_bytes}),
            )

    def select(self, key: int) -> bytes | None:
        return self._core.lookup_identity_encoded(self._namespace, key, "full")


class _ProxyManager(BaseManager):
    pass


def _serve_proxy(
    ready: Connection, address: str, authkey: bytes, entries: int, payload_bytes: int
) -> None:
    cache = _CoarseCache(entries, payload_bytes)
    _ProxyManager.register("cache", callable=lambda: cache)
    server = _ProxyManager(address=address, authkey=authkey).get_server()
    ready.send("ready")
    server.serve_forever()


def _measure(
    call: Callable[[int], object], keys: range, repetitions: PositiveInt
) -> Payload:
    process = psutil.Process()
    latencies: list[float] = []
    cpu_before = process.cpu_times()
    for _ in range(repetitions):
        for key in keys:
            started = time.perf_counter()
            call(key)
            latencies.append(time.perf_counter() - started)
    cpu_after = process.cpu_times()
    return _summary(
        latencies,
        cpu_after.user + cpu_after.system - cpu_before.user - cpu_before.system,
    )


async def _measure_async(
    call: Callable[[int], Awaitable[object]], keys: range, repetitions: PositiveInt
) -> Payload:
    process = psutil.Process()
    latencies: list[float] = []
    cpu_before = process.cpu_times()
    for _ in range(repetitions):
        for key in keys:
            started = time.perf_counter()
            await call(key)
            latencies.append(time.perf_counter() - started)
    cpu_after = process.cpu_times()
    return _summary(
        latencies,
        cpu_after.user + cpu_after.system - cpu_before.user - cpu_before.system,
    )


def _summary(latencies: list[float], worker_cpu: float) -> Payload:
    ordered = sorted(latencies)
    return {
        "calls": len(ordered),
        "median_us": statistics.median(ordered) * 1e6,
        "p99_us": ordered[int(0.99 * (len(ordered) - 1))] * 1e6,
        "caller_cpu_us_per_call": worker_cpu / len(ordered) * 1e6,
    }


def proxy_diagnostic(entries: int, payload_bytes: int, repetitions: int) -> Payload:
    directory = tempfile.mkdtemp(prefix="proxy-diagnostic-")
    address = f"{directory}/manager.sock"
    authkey = secrets.token_bytes(32)
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    server = context.Process(
        target=_serve_proxy, args=(child, address, authkey, entries, payload_bytes)
    )
    server.start()
    try:
        parent.recv()
        _ProxyManager.register("cache")
        manager = _ProxyManager(address=address, authkey=authkey)
        manager.connect()
        cache = manager.cache()  # type: ignore[attr-defined]

        def hit(key: int) -> object:
            return decode_value(cache.select(key))

        return _measure(hit, range(entries), repetitions)
    finally:
        server.terminate()
        server.join(10)


def socket_diagnostics(
    registration: Registration, entries: int, repetitions: int
) -> Payload:
    database = cast("str", registration.raw["database"])
    collection = cast("str", registration.raw["collection"])
    profile = {"documents": entries, "payload_bytes": 4096, "read": "find_one"}
    with IsolatedReplicaSet(ResourceLimits(cpus=2, memory="2g")) as replica:
        with MongoClient[dict[str, object]](replica.uri) as client:
            seed_catalogue(
                client,
                database=database,
                collection=collection,
                seed=cast("int", registration.raw["seed"]),
                profile=profile,  # type: ignore[arg-type]
                categories=64,
            )
        directory = tempfile.mkdtemp(prefix="socket-diagnostic-")
        config = owner_config(
            registration, replica.uri, directory, secrets.token_bytes(32)
        )
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        owner = context.Process(target=owner_main, args=(config, child))
        owner.start()
        child.close()
        parent.recv()
        try:
            return _socket_measurements(
                attachment_for(config), database, collection, entries, repetitions
            )
        finally:
            parent.send("close")
            parent.recv()
            owner.join(10)


def _socket_measurements(
    attachment: object, database: str, collection: str, entries: int, repetitions: int
) -> Payload:
    sync_endpoint = SyncEndpoint(attachment)  # type: ignore[arg-type]
    shape = encode_key(
        canonicalize(
            find_one_read_shape(None, None, None, codec_fingerprint(CodecOptions()))
        )
    )
    namespace = [database, collection]
    metadata = cast(
        "Payload", sync_endpoint.request({"op": "metadata", "ns": namespace})
    )
    deadline = time.monotonic() + 30
    while metadata["r"] != "ok" and time.monotonic() < deadline:
        time.sleep(0.05)
        metadata = cast(
            "Payload", sync_endpoint.request({"op": "metadata", "ns": namespace})
        )
    epoch = metadata["epoch"]

    def message(key: int) -> Message:
        return {
            "op": "select-identity",
            "ns": namespace,
            "epoch": epoch,
            "identity": encode_key(key),
            "shape": shape,
        }

    for key in range(entries):
        reply = cast("Payload", sync_endpoint.request(message(key)))
        sync_endpoint.send(
            {
                "op": "admit",
                "handle": reply["handle"],
                "value": encode_value({"_id": key, "payload": "x" * 4096}),
            }
        )

    def sync_hit(key: int) -> object:
        reply = cast("Payload", sync_endpoint.request(message(key)))
        return decode_value(cast("bytes", reply["value"]))

    payload: Payload = {"socket_sync": _measure(sync_hit, range(entries), repetitions)}

    async def asynchronous() -> Payload:
        endpoint = await AsyncEndpoint.attach(attachment)  # type: ignore[arg-type]

        async def loop_hit(key: int) -> object:
            reply = cast("Payload", await endpoint.request(message(key)))
            return decode_value(cast("bytes", reply["value"]))

        async def executor_hit(key: int) -> object:
            return await asyncio.to_thread(sync_hit, key)

        measured: Payload = {
            "socket_async_event_loop": await _measure_async(
                loop_hit, range(entries), repetitions
            ),
            "socket_async_thread_executor": await _measure_async(
                executor_hit, range(entries), repetitions
            ),
        }
        await endpoint.close()
        return measured

    payload.update(asyncio.run(asynchronous()))
    sync_endpoint.close()
    return payload


def profile_cells(
    registration: Registration, phase: str, workers: PositiveInt, model: str
) -> tuple[Cell, ...]:
    return tuple(
        cell
        for cell in comparison_cells(registration, phase)
        if cell.block == 0 and cell.workers == workers and cell.model == model
    )


def profile_windows(
    registration: Registration, cells: tuple[Cell, ...]
) -> list[Payload]:
    directory = Path(tempfile.mkdtemp(prefix="shared-cache-profile-"))
    os.environ[PROFILE_DIRECTORY] = str(directory)
    payloads: list[Payload] = []
    try:
        with IsolatedReplicaSet(
            ResourceLimits(**registration.section("topology"))  # type: ignore[arg-type]
        ) as replica:
            for cell in cells:
                record = run_window(replica, registration, cell)
                profiles = sorted(directory.glob("*.prof"))
                payloads.append(
                    {
                        "path": cell.path,
                        "workers": cell.workers,
                        "model": cell.model,
                        "populations": record["populations"],
                        "completed": record["completed"],
                        "owner_busy_seconds": _owner_busy(record),
                        "profiles": {
                            profile.stem.rsplit("-", 1)[0]: summarize(profile)
                            for profile in profiles
                        },
                    }
                )
                for profile in profiles:
                    profile.unlink()
    finally:
        del os.environ[PROFILE_DIRECTORY]
    return payloads


def _owner_busy(record: Payload) -> object:
    try:
        owner = cast("Payload", record["owner"])
    except KeyError:
        return None
    before = cast("Payload", cast("Payload", owner["before"])["counters"])
    after = cast("Payload", cast("Payload", owner["observation"])["counters"])
    return cast("float", after["busy_seconds"]) - cast("float", before["busy_seconds"])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=_LABEL)
    parser.add_argument("--config", type=Path, default=_CONFIG)
    parser.add_argument("--entries", type=int, default=1024)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--profile", nargs=3, metavar=("PHASE", "WORKERS", "MODEL"))
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    registration = Registration.load(arguments.config)
    report: Payload = {"label": _LABEL, "configuration_sha256": registration.digest}
    if arguments.profile is not None:
        phase, workers, model = arguments.profile
        report["windows"] = profile_windows(
            registration, profile_cells(registration, phase, int(workers), model)
        )
    else:
        report["proxy_coarse_operation"] = proxy_diagnostic(
            arguments.entries, 4096, arguments.repetitions
        )
        report.update(
            socket_diagnostics(registration, arguments.entries, arguments.repetitions)
        )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
