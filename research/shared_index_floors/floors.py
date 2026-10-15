from __future__ import annotations

import argparse
import asyncio
import json
import multiprocessing
import os
import platform
import random
import resource
import signal
import socket
import statistics
import struct
import subprocess
import sys
import tempfile
import threading
import time
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bson.codec_options import CodecOptions

from benchmarks.stream_cost.shared_cache.dataset import catalogue
from client_query_cache._core.canonical import canonicalize
from client_query_cache._core.codec import (
    codec_fingerprint,
    decode_value,
    encode_value,
)
from client_query_cache._core.find_one_reads import find_one_read_shape
from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.manager import CacheCore, CacheCoreConfig
from client_query_cache._core.order_sensitive_keys import order_sensitive_key
from client_query_cache._shared.wire import KeyCache, encode_key

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence
    from multiprocessing.connection import Connection
    from types import ModuleType

    from client_query_cache import _shared_index as native

type Payload = dict[str, Any]
type SyncHit = Callable[[int], object]
type AsyncHit = Callable[[int], Awaitable[object]]

LABEL = "exploratory floor diagnostic; excluded from promotion inference"
ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "reports/shared-worker-cache/v4/config.json"
MARGIN_US = 12.8
HITS = 5_120
REPETITIONS = 5
IN_FLIGHT = 4
TIMEOUT_SECONDS = 900
SLOTS = 32_768
ARENA_BYTES = 96 * 1024 * 1024
RING_TOKENS = 65_536
SWEEP_SECONDS = 0.05
KEY_CACHE_ENTRIES = 256
DATABASE = 0
NAMESPACE = 0
EPOCH = 1
FRAME = struct.Struct("<III")
SELECTION = struct.Struct("<IIQII")
LENGTH = struct.Struct("<I")
MISS = 0xFFFF_FFFF
RECEIVE_BYTES = 1_048_576 + 65_536
CELLS = (
    *(
        (floor, caller, mode)
        for floor in ("F0", "F1", "F2")
        for caller in ("sync", "async")
        for mode in ("sequential", "four")
    ),
    ("F3", "async", "four"),
)


def cpu_seconds() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_utime + usage.ru_stime


class Entries:
    __slots__ = ("identities", "options", "payloads", "read_shape", "shape")

    def __init__(self, config: Payload) -> None:
        profile = config["profiles"]["primary"]
        categories = config["profiles"]["find16"]["categories"]
        documents = list(catalogue(config["seed"], profile, categories))
        self.options: CodecOptions[Mapping[str, Any]] = CodecOptions()
        self.read_shape = canonicalize(
            find_one_read_shape(None, None, None, codec_fingerprint(self.options))
        )
        self.shape = encode_key(self.read_shape)
        self.payloads = [encode_value(document, self.options) for document in documents]
        self.identities = [
            encode_key(canonicalize(order_sensitive_key(document["_id"])))
            for document in documents
        ]


def identity_frame(request_id: int, identities: Sequence[bytes], shape: bytes) -> bytes:
    selections = b"".join(
        SELECTION.pack(DATABASE, NAMESPACE, EPOCH, len(identity), len(shape))
        + identity
        + shape
        for identity in identities
    )
    return (
        FRAME.pack(
            FRAME.size - LENGTH.size + len(selections), request_id, len(identities)
        )
        + selections
    )


def owner_main(
    index: native.OwnerIndex,
    ring: native.SessionRing,
    entries: Entries,
    socket_path: str,
    control: Connection,
) -> None:
    for identity, encoded in zip(entries.identities, entries.payloads, strict=True):
        payload = index.store(encoded)
        if payload is None or (
            index.publish(DATABASE, NAMESPACE, EPOCH, identity, entries.shape, payload)
            is None
        ):
            control.send("capacity")
            return
    index.set_epoch(NAMESPACE, EPOCH)
    index.set_available(DATABASE, available=True)
    index.set_progress(DATABASE, time.monotonic_ns())
    echo = index.serve(socket_path)
    control.send("ready")
    next_sweep = time.monotonic() + SWEEP_SECONDS
    try:
        while True:
            if control.poll(max(next_sweep - time.monotonic(), 0)):
                try:
                    message = control.recv()
                except EOFError:
                    return
                if message != "cpu":
                    return
                control.send(cpu_seconds())
            if time.monotonic() >= next_sweep:
                index.set_progress(DATABASE, time.monotonic_ns())
                ring.drain()
                next_sweep += SWEEP_SECONDS
    finally:
        echo.close()


class SyncCaller:
    __slots__ = ("_buffer", "_next_id", "_shape", "_socket", "_view")

    def __init__(self, path: str, shape: bytes) -> None:
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._socket.connect(path)
        self._shape = shape
        self._buffer = bytearray(RECEIVE_BYTES)
        self._view = memoryview(self._buffer)
        self._next_id = 0

    def select(self, identity: bytes) -> memoryview | None:
        self._next_id += 1
        self._socket.sendall(identity_frame(self._next_id, (identity,), self._shape))
        received = 0
        needed = LENGTH.size
        while received < needed:
            count = self._socket.recv_into(self._view[received:])
            if not count:
                raise ConnectionError("echo owner closed the connection")
            received += count
            if received >= LENGTH.size:
                needed = LENGTH.size + LENGTH.unpack_from(self._buffer)[0]
        (length,) = LENGTH.unpack_from(self._buffer, FRAME.size)
        if length == MISS:
            return None
        start = FRAME.size + LENGTH.size
        return self._view[start : start + length]

    def close(self) -> None:
        self._view.release()
        self._socket.close()


class AsyncCaller(asyncio.Protocol):
    __slots__ = (
        "_batch",
        "_inbox",
        "_next_id",
        "_pending",
        "_queued",
        "_shape",
        "_transport",
    )

    def __init__(self, shape: bytes, batch: int) -> None:
        self._shape = shape
        self._batch = batch
        self._inbox = bytearray()
        self._pending: dict[int, list[asyncio.Future[bytes | None]]] = {}
        self._queued: list[tuple[asyncio.Future[bytes | None], bytes]] = []
        self._next_id = 0
        self._transport: asyncio.Transport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        assert isinstance(transport, asyncio.Transport)
        self._transport = transport

    def data_received(self, chunk: bytes) -> None:
        inbox = self._inbox
        inbox += chunk
        offset = 0
        while len(inbox) - offset >= LENGTH.size:
            end = offset + LENGTH.size + LENGTH.unpack_from(inbox, offset)[0]
            if len(inbox) < end:
                break
            _length, request_id, _count = FRAME.unpack_from(inbox, offset)
            position = offset + FRAME.size
            for future in self._pending.pop(request_id):
                (length,) = LENGTH.unpack_from(inbox, position)
                position += LENGTH.size
                if length == MISS:
                    future.set_result(None)
                    continue
                future.set_result(bytes(inbox[position : position + length]))
                position += length
            offset = end
        del inbox[:offset]

    def _send(self, batch: list[tuple[asyncio.Future[bytes | None], bytes]]) -> None:
        assert self._transport is not None
        self._next_id += 1
        self._pending[self._next_id] = [future for future, _identity in batch]
        self._transport.write(
            identity_frame(
                self._next_id, [identity for _future, identity in batch], self._shape
            )
        )

    def _flush(self) -> None:
        queued, self._queued = self._queued, []
        for start in range(0, len(queued), self._batch):
            self._send(queued[start : start + self._batch])

    async def select(self, identity: bytes) -> bytes | None:
        future: asyncio.Future[bytes | None] = (
            asyncio.get_running_loop().create_future()
        )
        if self._batch == 1:
            self._send([(future, identity)])
        else:
            if not self._queued:
                asyncio.get_running_loop().call_soon(self._flush)
            self._queued.append((future, identity))
        return await future

    def close(self) -> None:
        assert self._transport is not None
        self._transport.close()


class Floors:
    __slots__ = (
        "core",
        "entries",
        "expiry_ns",
        "index",
        "keys",
        "misses",
        "namespace",
        "reader",
        "ring",
        "socket_path",
    )

    def __init__(
        self,
        entries: Entries,
        config: Payload,
        socket_path: str,
        native: ModuleType,
    ) -> None:
        self.entries = entries
        self.misses = 0
        self.core = CacheCore(
            CacheCoreConfig(
                shared_budget_bytes=config["budget_bytes"],
                max_entry_bytes=config["max_entry_bytes"],
            )
        )
        self.namespace = NamespaceId(config["database"], config["collection"])
        for key, payload in enumerate(entries.payloads):
            capture = self.core.begin_identity_admission(self.namespace, key)
            self.core.admit_identity_encoded(capture, entries.read_shape, payload)
        self.expiry_ns = int(config["transport"]["progress_expiry_seconds"] * 1e9)
        self.index = native.OwnerIndex(
            SLOTS, ARENA_BYTES, 1, 1, random.getrandbits(63), self.expiry_ns
        )
        self.ring = self.index.session_ring(RING_TOKENS)
        descriptor = self.index.reader_descriptor()
        try:
            self.reader = native.ReaderIndex(descriptor, self.ring.descriptor())
        finally:
            os.close(descriptor)
        self.ring.close_descriptor()
        self.keys = KeyCache(KEY_CACHE_ENTRIES)
        self.socket_path = socket_path

    def _decoded(self, payload: bytes | memoryview | None) -> object:
        if payload is None:
            self.misses += 1
            return None
        return decode_value(payload, self.entries.options)  # type: ignore[arg-type]

    def f0(self, key: int) -> object:
        lookup = self.core.lookup_identity(
            self.namespace,
            key,
            self.entries.read_shape,
            codec_options=self.entries.options,
        )
        if not lookup.hit:
            self.misses += 1
        return lookup.value

    def _identity(self, key: int) -> tuple[bytes, bytes]:
        return (
            encode_key(canonicalize(order_sensitive_key(key))),
            self.keys.encode(self.entries.read_shape),
        )

    def f1(self, key: int) -> object:
        identity, shape = self._identity(key)
        return self._decoded(
            self.reader.lookup(DATABASE, NAMESPACE, EPOCH, identity, shape)
        )

    def sync_hits(
        self, floor: str, callers: int
    ) -> tuple[list[SyncHit], Callable[[], None]]:
        if floor == "F0":
            return [self.f0] * callers, lambda: None
        if floor == "F1":
            return [self.f1] * callers, lambda: None
        connections = [
            SyncCaller(self.socket_path, self.entries.shape) for _ in range(callers)
        ]

        def remote(connection: SyncCaller) -> SyncHit:
            def hit(key: int) -> object:
                identity, _shape = self._identity(key)
                return self._decoded(connection.select(identity))

            return hit

        def close() -> None:
            for connection in connections:
                connection.close()

        return [remote(connection) for connection in connections], close

    async def async_hit(self, floor: str) -> tuple[AsyncHit, Callable[[], None]]:
        if floor in {"F0", "F1"}:
            local = self.f0 if floor == "F0" else self.f1

            async def hit_local(key: int) -> object:  # noqa: RUF029 - Match the awaitable interface of the socket-backed floors.
                return local(key)

            return hit_local, lambda: None
        _transport, protocol = await asyncio.get_running_loop().create_unix_connection(
            lambda: AsyncCaller(self.entries.shape, IN_FLIGHT if floor == "F3" else 1),
            self.socket_path,
        )

        async def hit_remote(key: int) -> object:
            identity, _shape = self._identity(key)
            return self._decoded(await protocol.select(identity))

        return hit_remote, protocol.close


def run_sync(hits: list[SyncHit], keys: list[int]) -> float:
    if len(hits) == 1:
        started = cpu_seconds()
        for key in keys:
            hits[0](key)
        return cpu_seconds() - started
    barrier = threading.Barrier(len(hits) + 1)

    def work(hit: SyncHit, part: list[int]) -> None:
        barrier.wait()
        for key in part:
            hit(key)

    threads = [
        threading.Thread(target=work, args=(hit, keys[offset :: len(hits)]))
        for offset, hit in enumerate(hits)
    ]
    for thread in threads:
        thread.start()
    started = cpu_seconds()
    barrier.wait()
    for thread in threads:
        thread.join()
    return cpu_seconds() - started


async def run_async(hit: AsyncHit, keys: list[int], tasks: int) -> float:
    async def work(part: list[int]) -> None:
        for key in part:
            await hit(key)

    started = cpu_seconds()
    await asyncio.gather(*(work(keys[offset::tasks]) for offset in range(tasks)))
    return cpu_seconds() - started


def measure(
    floors: Floors, control: Connection, repetition_keys: list[list[int]]
) -> list[Payload]:
    loop = asyncio.new_event_loop()
    sync_cells: dict[
        tuple[str, str, str], tuple[list[SyncHit], Callable[[], None]]
    ] = {}
    async_cells: dict[tuple[str, str, str], tuple[AsyncHit, Callable[[], None]]] = {}
    for cell in CELLS:
        floor, caller, mode = cell
        if caller == "sync":
            sync_cells[cell] = floors.sync_hits(
                floor, IN_FLIGHT if mode == "four" else 1
            )
        else:
            async_cells[cell] = loop.run_until_complete(floors.async_hit(floor))
    timed: dict[tuple[str, str, str], list[Payload]] = {cell: [] for cell in CELLS}
    for keys in repetition_keys:
        for cell in CELLS:
            floor, caller, mode = cell
            control.send("cpu")
            owner_before = control.recv()
            elapsed_before = time.perf_counter()
            if caller == "sync":
                caller_cpu = run_sync(sync_cells[cell][0], keys)
            else:
                caller_cpu = loop.run_until_complete(
                    run_async(
                        async_cells[cell][0], keys, IN_FLIGHT if mode == "four" else 1
                    )
                )
            elapsed = time.perf_counter() - elapsed_before
            control.send("cpu")
            owner_after = control.recv()
            owner_cpu = owner_after - owner_before if floor != "F0" else 0.0
            timed[cell].append(
                {
                    "hits": len(keys),
                    "elapsed_seconds": elapsed,
                    "caller_cpu_seconds": caller_cpu,
                    "owner_cpu_seconds": owner_cpu,
                    "cpu_per_hit_us": (caller_cpu + owner_cpu) / len(keys) * 1e6,
                }
            )
    for _hits, close in (*sync_cells.values(), *async_cells.values()):
        close()
    loop.run_until_complete(asyncio.sleep(0))
    loop.close()
    return [
        {
            "floor": floor,
            "caller": caller,
            "mode": mode,
            "repetitions": timed[floor, caller, mode][1:],
            "median_cpu_per_hit_us": statistics.median(
                row["cpu_per_hit_us"] for row in timed[floor, caller, mode][1:]
            ),
        }
        for floor, caller, mode in CELLS
    ]


def selection(cells: list[Payload], margin_us: float) -> Payload:
    medians: dict[tuple[str, str, str], float] = {
        (cell["floor"], cell["caller"], cell["mode"]): cell["median_cpu_per_hit_us"]
        for cell in cells
    }

    def statistic(floor: str, caller: str) -> float:
        return max(
            median
            for (cell_floor, cell_caller, _mode), median in medians.items()
            if (cell_floor, cell_caller) == (floor, caller)
        )

    reference = {caller: statistic("F0", caller) for caller in ("sync", "async")}
    local = {
        caller: statistic("F1", caller) - reference[caller] for caller in reference
    }
    native_sync = statistic("F2", "sync") - reference["sync"]
    async_sequential = medians["F2", "async", "sequential"] - reference["async"]
    async_unbatched = medians["F2", "async", "four"] - reference["async"]
    async_batched = medians["F3", "async", "four"] - reference["async"]
    native_async = max(async_sequential, min(async_unbatched, async_batched))
    a_eligible = all(cost <= margin_us for cost in local.values())
    b_eligible = native_sync <= margin_us and native_async <= margin_us
    return {
        "margin_us": margin_us,
        "f0_statistic_us": reference,
        "a_added_us": local,
        "b_added_us": {"sync": native_sync, "async": native_async},
        "b_async_terms_us": {
            "f2_sequential": async_sequential,
            "f2_four": async_unbatched,
            "f3_four": async_batched,
        },
        "a_eligible": a_eligible,
        "b_eligible": b_eligible,
        "b_needs_batching": b_eligible
        and max(async_sequential, async_unbatched) > margin_us,
        "build": ["A"] if a_eligible else (["B"] if b_eligible else []),
    }


def provenance() -> Payload:
    def command(*arguments: str) -> str:
        # Arguments come from the fixed provenance tool calls below; no shell is used.
        return subprocess.run(  # noqa: S603
            arguments, capture_output=True, text=True, check=True, cwd=ROOT
        ).stdout.strip()

    return {
        "revision": command("git", "rev-parse", "HEAD"),
        "dirty": bool(command("git", "status", "--porcelain")),
        "rustc": command("rustc", "--version"),
        "python": sys.version,
        "platform": platform.platform(),
        "processor": next(
            line.split(":", 1)[1].strip()
            for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines()
            if line.startswith("model name")
        ),
        "pymongo": version("pymongo"),
        "extension": version("client-query-cache"),
    }


def report() -> Payload:
    from client_query_cache import _shared_index as native  # noqa: PLC0415 - Load the optional prototype extension only when running the report.

    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    entries = Entries(config)
    directory = tempfile.mkdtemp(prefix="shared-index-floors-")
    socket_path = f"{directory}/echo.sock"
    floors = Floors(entries, config, socket_path, native)
    context = multiprocessing.get_context("fork")
    control, child = context.Pipe()
    owner = context.Process(
        target=owner_main, args=(floors.index, floors.ring, entries, socket_path, child)
    )
    owner.start()
    child.close()
    if control.recv() != "ready":
        message = "the floor prototype cannot hold every primary entry"
        raise RuntimeError(message)
    documents = len(entries.payloads)
    repetition_keys = [
        random.Random(config["seed"] * 1000 + repetition).sample(range(documents), HITS)
        for repetition in range(REPETITIONS + 1)
    ]
    try:
        cells = measure(floors, control, repetition_keys)
    finally:
        control.send("close")
        owner.join(10)
        Path(socket_path).unlink(missing_ok=True)
        Path(directory).rmdir()
    if floors.misses:
        message = f"{floors.misses} floor reads missed a resident entry"
        raise RuntimeError(message)
    sizes = [len(payload) for payload in entries.payloads]
    return {
        "label": LABEL,
        "provenance": provenance(),
        "configuration": {
            "hits": HITS,
            "repetitions": REPETITIONS,
            "in_flight": IN_FLIGHT,
            "entries": documents,
            "entry_min_bytes": min(sizes),
            "entry_max_bytes": max(sizes),
            "entry_total_bytes": sum(sizes),
            "slots": SLOTS,
            "arena_bytes": ARENA_BYTES,
            "ring_tokens": RING_TOKENS,
            "sweep_seconds": SWEEP_SECONDS,
            "expiry_ns": floors.expiry_ns,
        },
        "ring_dropped": floors.ring.dropped(),
        "cells": cells,
        "selection": selection(cells, MARGIN_US),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=LABEL)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    signal.alarm(TIMEOUT_SECONDS)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report(), indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
