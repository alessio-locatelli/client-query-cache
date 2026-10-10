# ruff: noqa: INP001, PLC0415
from __future__ import annotations

import argparse
import asyncio
import ctypes
import gc
import inspect
import json
import operator
import platform
import random
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import psutil

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


async def call(value: object) -> Any:  # noqa: ANN401
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


def sample(phase: str, manager: Any, **extra: object) -> None:  # noqa: ANN401
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
            "budget": snapshot.shared_budget_bytes,
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


async def read_codes(codes: Any, indexes: range, *, large: bool = False) -> None:  # noqa: ANN401
    for index in indexes:
        assert await call(codes.find_one(code_filter(index, large=large)))


async def read_category(catalogue: Any, category: int) -> list[object]:  # noqa: ANN401
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

    async def consume(cursor: Any) -> None:  # noqa: ANN401
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
                    shared_budget_bytes=BUDGETS[scenario],
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

    def checkpoint(phase: str, **extra: object) -> None:
        sample(phase, session[0], **extra)

    checkpoint("baseline", libc=platform.libc_ver())
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


def seed(control: Any) -> dict[str, object]:  # noqa: ANN401
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

    from research.collection_adapter.live_error import fixture

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
        "image": arguments.image,
        "host": platform.uname()._asdict(),
        "cpu_count": psutil.cpu_count(),
        "python": sys.version,
    }
    records: list[dict[str, object]] = []
    with fixture() as control:
        host, port = control.address
        uri = f"mongodb://{host}:{port}/?directConnection=true"
        report["dataset"] = seed(control)
        report["server"] = control.server_info()["version"]
        for run in range(arguments.runs):
            order.shuffle(cells)
            for scenario, api, mode in cells:
                output = engine.containers.run(
                    arguments.image,
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
                    remove=True,
                )
                records.extend(
                    json.loads(line)
                    | {"run": run, "scenario": scenario, "api": api, "mode": mode}
                    for line in output.decode().splitlines()
                )
                print(f"run {run}: {scenario} {api} {mode}", file=sys.stderr)
    report["records"] = records
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, indent=1))
    summarize(report)


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


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--runs", type=int, default=5)
    run.add_argument("--seed", type=int, default=197)
    run.add_argument("--image", default="docker.io/library/mongo:8.0.4-noble")
    run.add_argument("--scenarios", nargs="+", choices=SCENARIOS, default=[*SCENARIOS])
    run.add_argument("--output", type=Path, required=True)
    measured = commands.add_parser("child")
    measured.add_argument("uri")
    measured.add_argument("scenario", choices=SCENARIOS)
    measured.add_argument("api", choices=("sync", "async"))
    measured.add_argument("mode", choices=("direct", "cached"))
    summary = commands.add_parser("summarize")
    summary.add_argument("report", type=Path)
    arguments = parser.parse_args()
    if arguments.command == "run":
        coordinate(arguments)
    elif arguments.command == "summarize":
        summarize(json.loads(arguments.report.read_text()))
    else:
        asyncio.run(
            child(arguments.uri, arguments.scenario, arguments.api, arguments.mode)
        )


if __name__ == "__main__":
    main()
