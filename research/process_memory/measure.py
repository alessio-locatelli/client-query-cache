from __future__ import annotations

import argparse
import asyncio
import ctypes
import dataclasses
import gc
import inspect
import json
import operator
import platform
import random
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import psutil
from annotated_types import Ge

if TYPE_CHECKING:
    from collections.abc import Callable

DATABASE = "process_memory"
CATALOGUE = "catalogue"
CODES = "codes"
MIB = 1024 * 1024
CATEGORIES = 80
CATEGORY_DOCUMENTS = 224
CATALOGUE_DOCUMENTS = CATEGORIES * CATEGORY_DOCUMENTS
CODE_DOCUMENTS = 100_000
COLD_DOCUMENTS = 14_000
COLD_CATEGORIES = 64
RETAINED_CATEGORIES = 16
COLD_CODES = 64_000
PARTIAL_CURSORS = 32
PARTIAL_DOCUMENTS = 220
IN_VALUES = 48
CYCLES = 5
CYCLE_CODES = 40_000
BUDGETS = {
    "documents": 64 * MIB,
    "result-sets": 64 * MIB,
    "small-entries": 4 * MIB,
    "large-keys": 4 * MIB,
    "partial-cursors": 64 * MIB,
    "cycles": 1 * MIB,
}
MAX_ENTRY_BYTES = MIB
DELTAS = ("rss", "uss", "pss", "phase_peak_rss", "cgroup_current", "cgroup_anon")

type Checkpoint = Callable[..., None]
type Session = tuple[Any, Any, Any]


async def call(value: object) -> Any:
    return await value if inspect.isawaitable(value) else value


def _keyed(path: str, separator: str | None) -> dict[str, int]:
    fields: dict[str, int] = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return fields
    for line in lines:
        name, value = line.split(separator, 1)
        parts = value.split()
        if parts and parts[0].isdigit():
            fields[name.strip()] = int(parts[0])
    return fields


def _optional(fields: dict[str, int], name: str) -> int | None:
    try:
        return fields[name]
    except KeyError:
        return None


def _cgroup(name: str) -> int | None:
    try:
        return int(Path("/sys/fs/cgroup", name).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def sample(
    phase: str, manager: Any, budget_field: str = "budget_bytes", /, **extra: object
) -> None:
    gc.collect()
    peak = _keyed("/proc/self/status", ":")["VmHWM"] * 1024
    memory = psutil.Process().memory_full_info()
    stat = _keyed("/sys/fs/cgroup/memory.stat", None)
    record: dict[str, object] = {
        "phase": phase,
        "rss": memory.rss,
        "uss": memory.uss,
        "pss": memory.pss,
        "phase_peak_rss": peak,
        "cgroup_current": _cgroup("memory.current"),
        "cgroup_peak": _cgroup("memory.peak"),
        "cgroup_anon": _optional(stat, "anon"),
        "cgroup_file": _optional(stat, "file"),
        **extra,
    }
    if manager is not None:
        snapshot = manager.snapshot()
        record |= {
            "used_bytes": snapshot.used_bytes,
            "entries": snapshot.entry_count,
            "evictions": snapshot.evictions,
            "hits": snapshot.hits,
            "misses": snapshot.misses,
            "bypasses": snapshot.bypasses,
            "oversized_bypasses": snapshot.oversized_bypasses,
            "budget": getattr(snapshot, budget_field),
            "aliases": getattr(snapshot, "alias_count", None),
            "retention_declines": [
                dataclasses.asdict(item)
                for item in getattr(snapshot, "retention_declines", ())
            ],
        }
    record["objects"] = len(gc.get_objects())
    print(json.dumps(record), flush=True)
    Path("/proc/self/clear_refs").write_text("5", encoding="utf-8")


def code_filter(index: int, *, large: bool) -> dict[str, object]:
    code = f"C{index:07d}"
    if not large:
        return {"code": code}
    states = [f"state-{value:02d}-{index:07d}" for value in range(IN_VALUES - 1)]
    return {"code": code, "state": {"$in": [*states, "active"]}}


async def read_codes(codes: Any, indexes: range, *, large: bool = False) -> None:
    for index in indexes:
        assert await call(codes.find_one(code_filter(index, large=large)))


async def read_category(catalogue: Any, category: int) -> list[object]:
    cursor = catalogue.find({"attributes.category": category}).sort("_id", 1)
    documents: list[object] = await call(cursor.to_list())
    assert len(documents) == CATEGORY_DOCUMENTS
    return documents


async def documents(session: Session, checkpoint: Checkpoint) -> None:
    _, catalogue, _ = session
    for phase, identities in (
        ("cold", range(COLD_DOCUMENTS)),
        ("warm", range(COLD_DOCUMENTS)),
        ("evict", range(COLD_DOCUMENTS, CATALOGUE_DOCUMENTS)),
    ):
        for identity in identities:
            assert await call(catalogue.find_one({"_id": identity}))
        checkpoint(phase)


async def result_sets(session: Session, checkpoint: Checkpoint) -> None:
    _, catalogue, _ = session
    for phase in ("cold", "warm"):
        for category in range(COLD_CATEGORIES):
            await read_category(catalogue, category)
        checkpoint(phase)
    retained = [
        await read_category(catalogue, category)
        for category in range(RETAINED_CATEGORIES)
    ]
    checkpoint("retained")
    retained.clear()
    checkpoint("released")
    for category in range(COLD_CATEGORIES, CATEGORIES):
        await read_category(catalogue, category)
    checkpoint("evict")


async def code_phases(session: Session, checkpoint: Checkpoint, *, large: bool) -> None:
    _, _, codes = session
    for phase, indexes in (
        ("cold", range(COLD_CODES)),
        ("warm", range(COLD_CODES)),
        ("evict", range(COLD_CODES, CODE_DOCUMENTS)),
    ):
        await read_codes(codes, indexes, large=large)
        checkpoint(phase)


async def small_entries(session: Session, checkpoint: Checkpoint) -> None:
    await code_phases(session, checkpoint, large=False)


async def large_keys(session: Session, checkpoint: Checkpoint) -> None:
    await code_phases(session, checkpoint, large=True)


async def partial_cursors(session: Session, checkpoint: Checkpoint) -> None:
    _, catalogue, _ = session
    cursors = [
        catalogue.find({"attributes.category": category}).sort("_id", 1)
        for category in range(PARTIAL_CURSORS)
    ]

    async def consume(cursor: Any) -> None:
        for _ in range(PARTIAL_DOCUMENTS):
            await call(cursor.next())

    await asyncio.gather(*(consume(cursor) for cursor in cursors))
    captured = sum(
        capture.retained_bytes
        for cursor in cursors
        if (capture := getattr(cursor, "_capture", None)) is not None
    )
    checkpoint("partial", capture_bytes=captured)
    for cursor in cursors:
        await call(cursor.close())
    cursors.clear()
    checkpoint("closed")


SCENARIOS = {
    "documents": documents,
    "result-sets": result_sets,
    "small-entries": small_entries,
    "large-keys": large_keys,
    "partial-cursors": partial_cursors,
    "cycles": None,
}


async def child(uri: str, scenario: str, api: str, mode: str) -> None:
    from pymongo import AsyncMongoClient, MongoClient

    from benchmarks.implementation import implementation

    client: Any = (MongoClient if api == "sync" else AsyncMongoClient)(uri)

    async def open_session() -> Session:
        manager: Any = None
        database = client[DATABASE]
        if mode == "cached":
            from client_query_cache import CacheCoreConfig
            from client_query_cache import CacheManager as SyncManager
            from client_query_cache.asynchronous import CacheManager as AsyncManager

            manager = (SyncManager if api == "sync" else AsyncManager)(
                client,
                cache_config=CacheCoreConfig(
                    budget_bytes=BUDGETS[scenario],
                    max_entry_bytes=MAX_ENTRY_BYTES,
                ),
            )
            database = manager[DATABASE]
        catalogue, codes = database[CATALOGUE], database[CODES]
        await call(catalogue.find_one({"_id": -1}))
        deadline = time.monotonic() + 30
        while manager is not None and (
            manager.stream_health_snapshot(DATABASE).status != "healthy"
        ):
            if time.monotonic() > deadline:
                message = "change stream did not become healthy"
                raise RuntimeError(message)
            await asyncio.sleep(0.05)
        return manager, catalogue, codes

    session = await open_session()

    completed_phases: list[str] = []

    def checkpoint(phase: str, **extra: object) -> None:
        sample(phase, session[0], **extra)
        completed_phases.append(phase)

    actual = implementation(None if session[0] is None else session[0].cache_core)
    checkpoint("baseline", libc=platform.libc_ver(), implementation=actual)
    if scenario == "cycles":
        for cycle in range(CYCLES):
            if cycle:
                session = await open_session()
            await read_codes(session[2], range(CYCLE_CODES))
            checkpoint(f"cycle-{cycle}-filled")
            if session[0] is not None:
                await call(session[0].close())
            session = (None, None, None)
            checkpoint(f"cycle-{cycle}-closed")
    else:
        scenario_phases = SCENARIOS[scenario]
        assert scenario_phases is not None
        await scenario_phases(session, checkpoint)
    if session[0] is not None:
        await call(session[0].close())
    checkpoint("close")
    ctypes.CDLL(None).malloc_trim(0)
    checkpoint("trimmed")
    await call(client.close())
    print(json.dumps({"completed_phases": completed_phases}), flush=True)


def seed(control: Any) -> dict[str, object]:
    from benchmarks.stream_cost.shared_cache.dataset import seed_catalogue

    summary = seed_catalogue(
        control,
        database=DATABASE,
        collection=CATALOGUE,
        seed=197,
        profile={
            "documents": CATALOGUE_DOCUMENTS,
            "payload_bytes": 4096,
            "read": "process-memory",
        },
        categories=CATEGORIES,
    )
    database = control[DATABASE]
    database[CATALOGUE].create_index("attributes.category")
    codes = database[CODES]
    for start in range(0, CODE_DOCUMENTS, 10_000):
        codes.insert_many(
            {"_id": index, "code": f"C{index:07d}", "state": "active"}
            for index in range(start, start + 10_000)
        )
    codes.create_index("code")
    for name in (CATALOGUE, CODES):
        assert sum(1 for _ in database[name].find()) > 0
    return dict(summary)


def coordinate(arguments: argparse.Namespace) -> None:
    import docker

    from benchmarks.mongodb_image import MONGODB_IMAGE
    from research.collection_adapter.live_error import fixture

    image = arguments.image or MONGODB_IMAGE
    root = Path.cwd()
    mounts = {
        str(path): {"bind": str(path), "mode": "ro"}
        for path in {root, Path(sys.prefix), Path(sys.base_prefix)}
    }
    engine = docker.from_env()
    cells = [
        (scenario, api, mode)
        for scenario in arguments.scenarios
        for api in ("sync", "async")
        for mode in ("direct", "cached")
    ]
    order = random.Random(arguments.seed)
    report: dict[str, object] = {
        "started": datetime.now(UTC).isoformat(),
        "image": image,
        "host": platform.uname()._asdict(),
        "cpu_count": psutil.cpu_count(),
        "python": sys.version,
    }
    records: list[dict[str, object]] = []
    children = arguments.output.with_name(f"{arguments.output.stem}-children")
    children.mkdir(parents=True, exist_ok=True)
    with fixture(image) as control:
        address = control.address
        assert address is not None
        host, port = address
        uri = f"mongodb://{host}:{port}/?directConnection=true"
        report["dataset"] = seed(control)
        report["server"] = control.server_info()["version"]
        for run in range(arguments.runs):
            order.shuffle(cells)
            for scenario, api, mode in cells:
                container = engine.containers.run(
                    image,
                    [
                        "-m",
                        "research.process_memory.measure",
                        "child",
                        uri,
                        scenario,
                        api,
                        mode,
                    ],
                    entrypoint=sys.executable,
                    environment={"PYTHONDONTWRITEBYTECODE": "1"},
                    working_dir=str(root),
                    volumes=mounts,
                    network_mode="host",
                    security_opt=["label=disable"],
                    detach=True,
                )
                raw = children / f"{run}-{scenario}-{api}-{mode}.jsonl"
                try:
                    status = container.wait()["StatusCode"]
                    output = container.logs()
                    raw.write_bytes(output)
                    if status:
                        message = f"measured child exited with status {status}: {raw}"
                        raise RuntimeError(message)
                finally:
                    container.remove(v=True)
                frames = completed_frames(output, raw)
                records.extend(
                    frame | {"run": run, "scenario": scenario, "api": api, "mode": mode}
                    for frame in frames
                )
                print(f"run {run}: {scenario} {api} {mode}", file=sys.stderr)
    report["records"] = records
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, indent=1))
    summarize(report)


def completed_frames(output: bytes, raw: Path) -> list[dict[str, Any]]:
    frames = [json.loads(line) for line in output.decode().splitlines()]
    if not frames or "completed_phases" not in frames[-1]:
        message = f"missing child completion record: {raw}"
        raise RuntimeError(message)
    completed = frames.pop()["completed_phases"]
    if [frame["phase"] for frame in frames] != completed:
        message = f"incomplete child checkpoint stream: {raw}"
        raise RuntimeError(message)
    return frames


def _span(values: list[int], scale: int) -> str:
    if not values:
        return "-"
    median = statistics.median(values) / scale
    return f"{median:.1f} ({min(values) / scale:.1f}-{max(values) / scale:.1f})"


def _resident(record: dict[str, Any], field: str) -> int:
    try:
        return int(record[field])
    except KeyError:
        return 0


def summarize(report: dict[str, Any]) -> None:
    records: dict[tuple[str, str, str, str, int], dict[str, Any]] = {
        (
            record["scenario"],
            record["api"],
            record["phase"],
            record["mode"],
            record["run"],
        ): record
        for record in report["records"]
    }
    cells = sorted(
        dict.fromkeys(key[:3] for key in records), key=operator.itemgetter(0, 1)
    )
    runs = sorted({key[4] for key in records})
    print(
        "| Scenario | API | Phase | Direct RSS MiB | "
        + " | ".join(f"Δ{field} MiB" for field in DELTAS)
        + " | Cached BSON MiB | Entries | ΔRSS ÷ BSON | ΔRSS B/entry |"
    )
    for scenario, api, phase in cells:
        pairs = [
            (records[scenario, api, phase, "direct", run], records[cached])
            for run in runs
            if (cached := (scenario, api, phase, "cached", run)) in records
            and (scenario, api, phase, "direct", run) in records
        ]
        if not pairs:
            continue
        deltas = [
            _span(
                [
                    cached[field] - direct[field]
                    for direct, cached in pairs
                    if cached[field] is not None and direct[field] is not None
                ],
                MIB,
            )
            for field in DELTAS
        ]
        rss = statistics.median(
            cached["rss"] - direct["rss"] for direct, cached in pairs
        )
        used = statistics.median(_resident(cached, "used_bytes") for _, cached in pairs)
        entries = statistics.median(_resident(cached, "entries") for _, cached in pairs)
        print(
            f"| {scenario} | {api} | {phase} | "
            f"{_span([direct['rss'] for direct, _ in pairs], MIB)} | "
            + " | ".join(deltas)
            + f" | {used / MIB:.1f} | {entries:.0f} | "
            + (f"{rss / used:.2f}" if entries > 1 else "-")
            + " | "
            + (f"{rss / entries:.0f}" if entries > 1 else "-")
            + " |"
        )


def latency_summary(
    latencies: list[Annotated[int, Ge(0)]],
    wall: Annotated[float, Ge(0)],
    cpu: Annotated[float, Ge(0)],
) -> dict[str, object]:
    ordered = sorted(latencies)
    return {
        "operations": len(ordered),
        "wall_seconds": wall,
        "cpu_seconds": cpu,
        "p50_ns": ordered[(len(ordered) - 1) // 2],
        "p95_ns": ordered[(len(ordered) - 1) * 95 // 100],
        "p99_ns": ordered[(len(ordered) - 1) * 99 // 100],
    }


async def measured_reads(
    operation: Callable[[Annotated[int, Ge(0)]], object],
    indexes: range,
    repetitions: Annotated[int, Ge(1)] = 1,
) -> dict[str, object]:
    latencies = []
    cpu = time.process_time()
    wall = time.perf_counter()
    for _ in range(repetitions):
        for index in indexes:
            start = time.perf_counter_ns()
            assert await call(operation(index)) is not None
            latencies.append(time.perf_counter_ns() - start)
    return latency_summary(
        latencies, time.perf_counter() - wall, time.process_time() - cpu
    )


async def retention_child(arguments: argparse.Namespace) -> None:
    from pymongo import AsyncMongoClient, MongoClient
    from pymongo.monitoring import CommandListener

    from client_query_cache import CacheCoreConfig
    from client_query_cache import CacheManager as SyncManager
    from client_query_cache._core.keys import NamespaceId  # noqa: PLC2701 - Qualification clears the measured namespace between phases.
    from client_query_cache.asynchronous import CacheManager as AsyncManager

    class OriginCommands(CommandListener):
        __slots__ = ("count",)

        def __init__(self) -> None:
            self.count = 0

        def started(self, event: Any) -> None:
            if event.database_name == DATABASE and event.command_name == "find":
                self.count += 1

        def succeeded(self, event: Any) -> None:
            pass

        def failed(self, event: Any) -> None:
            pass

    observer = OriginCommands()
    client: Any = (MongoClient if arguments.api == "sync" else AsyncMongoClient)(
        arguments.uri, event_listeners=[observer]
    )
    config = {
        arguments.budget_field: arguments.budget,
        "max_entry_bytes": min(arguments.budget, MIB),
    }
    if arguments.max_entries is not None:
        config["max_entries"] = arguments.max_entries
    if arguments.max_key_bytes is not None:
        config["max_key_bytes"] = arguments.max_key_bytes
    manager: Any = (SyncManager if arguments.api == "sync" else AsyncManager)(
        client, cache_config=CacheCoreConfig(**config)
    )
    view = manager[DATABASE][CODES]
    completed = []

    def checkpoint(phase: str, **extra: object) -> None:
        alias_count = getattr(manager.snapshot(), "alias_count", None)
        if alias_count is None:
            alias_count = manager.cache_core._ownership()[2]  # noqa: SLF001 - Frozen builds expose alias occupancy only through this diagnostic.
        sample(
            phase,
            manager,
            arguments.budget_field,
            origins=observer.count,
            live_aliases=alias_count,
            **extra,
        )
        completed.append(phase)

    # Stream startup and index metadata discovery are outside measured phases.
    deadline = time.monotonic() + 30
    while True:
        before = manager.snapshot().hits
        await call(view.find_one({"code": "C0000000"}))
        if manager.snapshot().hits > before:
            break
        if time.monotonic() > deadline:
            raise RuntimeError("retention preflight did not become warm")
        await asyncio.sleep(0.01)
    manager.cache_core.clear_namespace(NamespaceId(DATABASE, CODES))
    if arguments.prefill:
        for index in range(2048, 2048 + 8):
            await call(view.find_one({"code": f"C{index:07d}"}))
        for index in range(4096, 4096 + arguments.prefill):
            await call(view.find_one({"_id": index}))
    checkpoint("baseline", python=sys.version, limits=config, api=arguments.api)
    large = arguments.scenario == "large-keys"

    def read(index: Annotated[int, Ge(0)]) -> object:
        query = code_filter(index, large=large)
        if arguments.single_identity:
            query["code"] = f"S{index:07d}"
        return view.find_one(query)

    checkpoint("cold", **await measured_reads(read, range(arguments.distinct)))
    # The known retained suffix is the hit control under count pressure.
    checkpoint(
        "warm",
        **await measured_reads(
            read,
            range(arguments.distinct - arguments.retained, arguments.distinct),
            arguments.warm_repeats,
        ),
    )
    checkpoint(
        "repeat",
        **await measured_reads(
            read,
            range(arguments.distinct - arguments.retained, arguments.distinct),
            arguments.warm_repeats,
        ),
    )
    if arguments.unique:
        checkpoint(
            "identity",
            **await measured_reads(
                lambda index: view.find_one(
                    {"_id": 8194 if arguments.single_identity else index}
                ),
                range(arguments.distinct - arguments.retained, arguments.distinct),
                arguments.warm_repeats,
            ),
        )
        for label, identity in (
            ("unrelated", arguments.distinct + 1),
            ("matched", 8194 if arguments.single_identity else arguments.distinct - 1),
        ):
            before = manager.cache_core.stream_cost_snapshot(DATABASE).invalidations
            await call(
                view.raw.update_one({"_id": identity}, {"$inc": {"revision": 1}})
            )
            deadline = time.monotonic() + 30
            while (
                manager.cache_core.stream_cost_snapshot(DATABASE).invalidations
                <= before
            ):
                if time.monotonic() > deadline:
                    raise RuntimeError("retention write invalidation did not arrive")
                await asyncio.sleep(0.005)
            checkpoint(
                label,
                **await measured_reads(
                    read,
                    range(arguments.distinct - arguments.retained, arguments.distinct),
                    arguments.warm_repeats,
                ),
            )
    manager.cache_core.clear_namespace(NamespaceId(DATABASE, CODES))
    checkpoint("clear")
    await call(manager.close())
    checkpoint("close")
    await call(client.close())
    print(json.dumps({"completed_phases": completed}), flush=True)


def retention_core(arguments: argparse.Namespace) -> None:
    from client_query_cache import CacheCoreConfig
    from client_query_cache._core.keys import NamespaceId, canonical_alias_key  # noqa: PLC2701 - Measure complete internal alias admission and reclamation.
    from client_query_cache._core.manager import CacheCore  # noqa: PLC2701 - Compare the reference and native ownership implementations.
    from client_query_cache._shared_index import LocalCacheCore  # noqa: PLC2701 - Compare the reference and native ownership implementations.

    completed = []

    def checkpoint(phase: str, core: Any, **extra: object) -> None:
        sample(phase, core, arguments.budget_field, **extra)
        completed.append(phase)

    constructor = CacheCore if arguments.core == "reference" else LocalCacheCore
    namespace = NamespaceId(DATABASE, CODES)
    if arguments.scenario == "aliases":
        for count in (256, 1024, 4096):
            config: dict[str, Any] = {
                arguments.budget_field: arguments.budget,
                "max_entry_bytes": MIB,
            }
            if arguments.enabled:
                config["max_entries"] = count + 2
            core = constructor(CacheCoreConfig(**config))
            aliases = [
                canonical_alias_key("code", f"C{index:07d}", None)
                for index in range(count)
            ]
            for cycle in range(3):
                core.admit_identity(
                    core.begin_identity_admission(namespace, "A"), "full", 1
                )
                pin = core.begin_identity_admission(namespace, "A")
                wall, cpu = time.perf_counter(), time.process_time()
                latencies = []
                for alias in aliases:
                    start = time.perf_counter_ns()
                    core.admit_identity(
                        core.begin_identity_admission(namespace, "A"),
                        "full",
                        1,
                        alias=alias,
                    )
                    latencies.append(time.perf_counter_ns() - start)
                checkpoint(
                    "published",
                    core,
                    count=count,
                    cycle=cycle,
                    **latency_summary(
                        latencies, time.perf_counter() - wall, time.process_time() - cpu
                    ),
                )
                assert all(
                    core.resolve_alias(namespace, "code", f"C{index:07d}", None) == "A"
                    for index in range(count)
                )
                capture = core.capture_namespace_generation(namespace)
                wall, cpu = time.perf_counter(), time.process_time()
                latencies = []
                for alias in aliases:
                    start = time.perf_counter_ns()
                    core.discard_stale_alias(capture, alias, "A")
                    latencies.append(time.perf_counter_ns() - start)
                checkpoint(
                    "removed",
                    core,
                    count=count,
                    cycle=cycle,
                    **latency_summary(
                        latencies, time.perf_counter() - wall, time.process_time() - cpu
                    ),
                )
                pin.release()
                core.clear_namespace(namespace)
                checkpoint("released", core, count=count, cycle=cycle)
            core.close()
    else:
        config = {arguments.budget_field: arguments.budget, "max_entry_bytes": MIB}
        if arguments.enabled:
            config["max_entries"] = arguments.max_entries
        core = constructor(CacheCoreConfig(**config))
        barrier = threading.Barrier(arguments.threads)

        def admit(worker: Annotated[int, Ge(0)]) -> list[Annotated[int, Ge(0)]]:
            target = NamespaceId(DATABASE, f"namespace-{worker % 2}")
            barrier.wait(timeout=30)
            latencies = []
            for index in range(arguments.distinct):
                start = time.perf_counter_ns()
                core.admit_namespace(
                    core.capture_namespace_generation(target), (worker, index), index
                )
                latencies.append(time.perf_counter_ns() - start)
            return latencies

        wall, cpu = time.perf_counter(), time.process_time()
        with ThreadPoolExecutor(max_workers=arguments.threads) as pool:
            timings = list(pool.map(admit, range(arguments.threads)))
        checkpoint(
            "contention",
            core,
            threads=arguments.threads,
            **latency_summary(
                [latency for group in timings for latency in group],
                time.perf_counter() - wall,
                time.process_time() - cpu,
            ),
        )
        core.close()
        checkpoint("close", core)
    print(json.dumps({"completed_phases": completed}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--runs", type=int, default=5)
    run.add_argument("--seed", type=int, default=197)
    run.add_argument("--image", help="server and measured-process image")
    run.add_argument("--scenarios", nargs="+", choices=SCENARIOS, default=[*SCENARIOS])
    run.add_argument("--output", type=Path, required=True)
    measured = commands.add_parser("child")
    measured.add_argument("uri")
    measured.add_argument("scenario", choices=SCENARIOS)
    measured.add_argument("api", choices=("sync", "async"))
    measured.add_argument("mode", choices=("direct", "cached"))
    retention = commands.add_parser("retention-child")
    retention.add_argument("uri")
    retention.add_argument("--api", choices=("sync", "async"), default="sync")
    retention.add_argument(
        "--scenario", choices=("small-entries", "large-keys"), default="small-entries"
    )
    retention.add_argument("--distinct", type=int, default=8192)
    retention.add_argument("--retained", type=int, default=4096)
    retention.add_argument("--budget", type=int, default=4 * MIB)
    retention.add_argument("--max-entries", type=int)
    retention.add_argument("--max-key-bytes", type=int)
    retention.add_argument("--unique", action="store_true")
    retention.add_argument("--warm-repeats", type=int, default=1)
    retention.add_argument("--prefill", type=int, default=0)
    retention.add_argument("--single-identity", action="store_true")
    core = commands.add_parser("retention-core")
    core.add_argument("--core", choices=("native", "reference"), default="native")
    core.add_argument(
        "--scenario", choices=("aliases", "contention"), default="aliases"
    )
    core.add_argument("--enabled", action="store_true")
    core.add_argument("--threads", type=int, choices=(1, 4), default=1)
    core.add_argument("--distinct", type=int, default=8192)
    core.add_argument("--max-entries", type=int, default=1024)
    core.add_argument("--budget", type=int, default=MIB)
    for qualification in (retention, core):
        qualification.add_argument(
            "--budget-field",
            choices=("budget_bytes", "shared_budget_bytes"),
            default="budget_bytes",
        )
    summary = commands.add_parser("summarize")
    summary.add_argument("report", type=Path)
    arguments = parser.parse_args()
    if arguments.command == "retention-child" and (
        not 0 < arguments.retained <= arguments.distinct
        or arguments.warm_repeats < 1
        or arguments.prefill < 0
    ):
        parser.error(
            "require 0 < retained <= distinct, warm-repeats >= 1 and prefill >= 0"
        )
    if arguments.command == "retention-child":
        asyncio.run(retention_child(arguments))
    elif arguments.command == "retention-core":
        retention_core(arguments)
    elif arguments.command == "run":
        coordinate(arguments)
    elif arguments.command == "summarize":
        summarize(json.loads(arguments.report.read_text()))
    else:
        asyncio.run(
            child(
                arguments.uri,
                arguments.scenario,
                arguments.api,
                arguments.mode,
            )
        )


if __name__ == "__main__":
    main()
