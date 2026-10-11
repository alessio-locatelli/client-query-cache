from __future__ import annotations

import asyncio
import copy
import json
import shutil
import time
import zlib
from dataclasses import asdict, replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from benchmarks.stream_cost.errors import (
    BenchmarkConfigurationError,
    BenchmarkSetupError,
)
from benchmarks.stream_cost.shared_cache import analysis, run, window
from benchmarks.stream_cost.shared_cache.dataset import (
    catalogue,
    checksum,
    seed_catalogue,
)
from benchmarks.stream_cost.shared_cache.protocol import (
    BASELINES,
    Registration,
    capacity_cells,
    comparison_cells,
    path_order,
    probe_cells,
    smoke_cells,
    validation_cells,
    validation_failure,
    window_for,
    write_count,
)
from benchmarks.stream_cost.shared_cache.workload import (
    Assignment,
    LoopResult,
    closed_loop_async,
    closed_loop_sync,
    key_order,
    open_loop_async,
    open_loop_sync,
    worker_keys,
)
from client_query_cache._types import BsonDict, JsonDict, NonNegativeInt

if TYPE_CHECKING:
    from collections.abc import Callable

    from benchmarks.stream_cost.shared_cache.protocol import Cell, PathKind
    from benchmarks.stream_cost.shared_cache.worker import WorkerSpec

pytestmark = pytest.mark.unit

_CONFIG = Path("reports/shared-worker-cache/v4/config.json")
_V4_COMPANION = Path("reports/shared-worker-cache/v4/registration.md")
_FROZEN_RATES = {"primary": 3000, "cold": 1000, "sensitivity": 500}
_FROZEN_WINDOWS = {"hot": 30, "active": 60, "sensitivity": 30}
_CONCURRENT_CONFIG = Path("reports/concurrent-worker-workload/v1/config.json")
_CONCURRENT_RATE = 1000
_CONCURRENT_CELLS = {
    ("active", "async", workers, path)
    for workers in (1, 4)
    for path in ("direct", "independent")
}


@pytest.fixture
def registration() -> Registration:
    frozen = Registration.load(_CONFIG)
    raw = copy.deepcopy(frozen.raw)
    raw["status"] = "pending-calibration"
    raw["frozen"] = {
        "rates": dict.fromkeys(_FROZEN_RATES),
        "window_seconds": dict.fromkeys(_FROZEN_WINDOWS),
        "calibration_summary": None,
    }
    return replace(frozen, raw=raw)


@pytest.fixture
def frozen(registration: Registration) -> Registration:
    raw = copy.deepcopy(registration.raw)
    raw["status"] = "frozen"
    raw["frozen"] = {
        "rates": _FROZEN_RATES,
        "window_seconds": _FROZEN_WINDOWS,
        "calibration_summary": {},
    }
    return replace(registration, raw=raw)


def _restated(
    registration: Registration, status: str, frozen: JsonDict
) -> Registration:
    raw = copy.deepcopy(registration.raw)
    raw["status"] = status
    raw["frozen"] = frozen
    return replace(registration, raw=raw)


@pytest.fixture
def concurrent() -> Registration:
    return _restated(
        Registration.load(_CONCURRENT_CONFIG),
        "pending-calibration",
        {
            "rates": {"steady": None},
            "window_seconds": {"active": None},
            "calibration_summary": None,
        },
    )


@pytest.fixture
def concurrent_frozen(concurrent: Registration) -> Registration:
    return _restated(
        concurrent,
        "frozen",
        {
            "rates": {"steady": _CONCURRENT_RATE},
            "window_seconds": {"active": 60},
            "calibration_summary": {},
        },
    )


def _record(
    cell: Cell,
    *,
    completed: int = 1_000,
    hits: int | None = None,
    misses: int | None = None,
    p99: float = 0.001,
    pss: float = 100.0,
    cpu: float = 1.0,
    healthy: bool = True,
) -> JsonDict:
    sample_count = 20_000
    loop = {
        "offered": completed,
        "completed": completed,
        "completed_in_window": completed,
        "errors": 0,
        "overflow": 0,
        "outstanding_at_end": 0,
        "elapsed": 10.0,
    }
    worker: JsonDict = {
        "model": "sync",
        "cpu_seconds": cpu,
        "drain_cpu_seconds": 0.0,
        "wire_sent": 10,
        "wire_received": 10,
        "outcomes": {
            "hits": (0 if cell.workload == "cold" else completed)
            if hits is None
            else hits,
            "misses": (
                completed if cell.workload == "cold" and cell.path != "direct" else 0
            )
            if misses is None
            else misses,
            "bypasses": 0,
            "bypass_reasons": {},
        },
        "streams": 1 if cell.path == "independent" else 0,
        "loop": loop,
        "lag": {"lag_windows": [[0.01, 0.02]]},
    }
    population = {
        "sample_count": sample_count,
        "p50_seconds": p99 / 4,
        "p95_seconds": p99 / 2,
        "p99_seconds": p99,
    }
    record: JsonDict = {
        **asdict(cell),
        "healthy": healthy,
        "offered": completed,
        "completed": completed,
        "completed_in_window": completed,
        "workers_measured": [worker],
        "memory": {"steady_group_pss_bytes": pss, "peak_group_pss_bytes": pss * 1.1},
        "server_memory_bytes": 10.0,
        "server_cpu_seconds": 0.0,
        "server_drain_cpu_seconds": 0.0,
        "harness_cpu_seconds": 0.5,
        "populations": {"request": population, "sync": population, "async": population},
        "clock_offset_seconds": 0.0,
        "clock_uncertainty_seconds": 0.001,
    }
    if not healthy:
        record["failure"] = "deliberate failure"
    if cell.path == "shared":
        record["owner"] = {
            "cpu_seconds": 0.0,
            "drain_cpu_seconds": 0.0,
            "wire_sent": 0,
            "wire_received": 0,
            "lag_windows": [[0.01, 0.03]],
            "commands": {"stream:opened": 0},
            "health": "healthy",
        }
    return record


@pytest.mark.parametrize(
    ("phase", "expected"),
    [
        pytest.param("screening", 6 * 3 * 2 * 3, id="screening"),
        pytest.param("confirmation", 12 * 2 * 2 * 3, id="confirmation"),
        pytest.param("active", 12 * 5 * 3, id="active"),
        pytest.param("cold", 12 * 2 * 2 * 3, id="cold"),
        pytest.param("sensitivity", 3 * 2 * 2 * 3, id="sensitivity"),
    ],
)
def test_comparison_phases_plan_every_registered_cell(
    frozen: Registration, phase: str, expected: int
) -> None:
    cells = comparison_cells(frozen, phase)

    assert len(cells) == expected
    assert {cell.path for cell in cells} == set(frozen.paths)


def test_twelve_blocks_use_every_path_order_twice(frozen: Registration) -> None:
    orders = [path_order(block, frozen.paths) for block in range(12)]

    assert all(orders.count(order) == 2 for order in set(orders))
    assert len(set(orders)) == 6
    assert comparison_cells(frozen, "confirmation", BASELINES)[0].path == "direct"


def test_capacity_staircase_covers_counts_models_and_concurrency(
    registration: Registration,
) -> None:
    cells = capacity_cells(registration)

    assert len(cells) == 3 * 3 * 2 * 3 * 3
    assert {cell.concurrency for cell in cells} == {1, 4, 16}
    assert {cell.loop for cell in cells} == {"closed"}


def test_calibration_never_plans_a_candidate_path(registration: Registration) -> None:
    probes = probe_cells(registration)
    validations = validation_cells(
        registration, "primary", 100.0, {"hot": 30.0, "active": 60.0}
    )

    assert {cell.path for cell in (*probes, *validations)} == set(BASELINES)
    assert len(probes) == 19 * 3 * 2
    assert {cell.loop for cell in probes} == {"closed"}
    assert {cell.loop for cell in validations} == {"open"}


def test_smoke_cells_cover_each_workload_and_model(registration: Registration) -> None:
    cells = smoke_cells(registration)

    assert {(cell.workload, cell.model) for cell in cells} == {
        ("hot", "sync"),
        ("active", "mixed"),
        ("cold", "async"),
    }
    assert all(cell.identities == 100 for cell in cells if cell.workload == "cold")


@pytest.mark.parametrize(
    ("kind", "rate", "populations", "expected"),
    [
        pytest.param("hot", 3000.0, 1, 30, id="nominal-hot"),
        pytest.param("hot", 100.0, 1, 102, id="sample-floor-extends-hot"),
        pytest.param("active", 300.0, 2, 68, id="mixed-needs-both-models"),
    ],
)
def test_window_preserves_the_percentile_sample_floor(
    registration: Registration,
    kind: str,
    rate: float,
    populations: int,
    expected: float,
) -> None:
    assert window_for(registration, kind, rate, populations) == expected


def test_unfrozen_registration_rejects_candidate_planning(
    registration: Registration,
) -> None:
    with pytest.raises(BenchmarkConfigurationError, match="no frozen hot window"):
        comparison_cells(registration, "screening")
    with pytest.raises(BenchmarkConfigurationError, match="no frozen primary rate"):
        registration.rate("primary")


@pytest.mark.parametrize(
    ("family", "ceiling", "expected"),
    [
        pytest.param("primary", None, 750, id="weakest-baseline"),
        pytest.param("cold", 600.0, 600, id="capped-by-primary"),
        pytest.param("sensitivity", None, 500, id="family-cap"),
    ],
)
def test_rate_uses_the_weakest_baseline_probe(
    registration: Registration, family: str, ceiling: float | None, expected: int
) -> None:
    cell = probe_cells(registration)[0]
    probes = [_record(cell, completed=completed) for completed in (10_000, 20_000)]

    assert run.select_rate(registration, family, probes, ceiling) == expected


def _late(record: JsonDict) -> None:
    record["completed_in_window"] = 900


def _first_loop(record: JsonDict) -> JsonDict:
    return cast(
        "JsonDict", cast("list[JsonDict]", record["workers_measured"])[0]["loop"]
    )


def _failed_read(record: JsonDict) -> None:
    _first_loop(record)["errors"] = 1


def _overflowed(record: JsonDict) -> None:
    _first_loop(record)["overflow"] = 1


def _backlogged(record: JsonDict) -> None:
    _first_loop(record)["outstanding_at_end"] = 9


def _undersampled(record: JsonDict) -> None:
    populations = cast("JsonDict", record["populations"])
    cast("JsonDict", populations["request"])["sample_count"] = 9_999


@pytest.mark.parametrize(
    ("alter", "reason"),
    [
        pytest.param(_late, "registered fraction", id="late"),
        pytest.param(_failed_read, "overflow", id="errors"),
        pytest.param(_overflowed, "overflow", id="overflow"),
        pytest.param(_backlogged, "backlog", id="backlog"),
        pytest.param(_undersampled, "sample floor", id="samples"),
    ],
)
def test_validation_rejects_overloaded_or_short_windows(
    registration: Registration, alter: Callable[[JsonDict], None], reason: str
) -> None:
    cell = validation_cells(
        registration, "primary", 100.0, {"hot": 30.0, "active": 60.0}
    )[0]
    record = _record(cell)
    alter(record)

    failure = validation_failure(record, registration)

    assert failure is not None
    assert reason in failure


_NOT_MISSES = "cold window recorded hits or bypasses instead of misses"


@pytest.mark.parametrize(
    ("path", "completed", "outcomes", "expected"),
    [
        pytest.param("independent", 10_000, {}, None, id="all-miss"),
        pytest.param("direct", 10_000, {}, None, id="direct"),
        pytest.param(
            "independent",
            9_999,
            {},
            "cold window did not complete every identity",
            id="short",
        ),
        pytest.param(
            "independent", 10_000, {"hits": 1, "misses": 9_999}, _NOT_MISSES, id="hit"
        ),
        pytest.param(
            "independent",
            10_000,
            {"misses": 0, "bypasses": 10_000},
            _NOT_MISSES,
            id="bypassed",
        ),
    ],
)
def test_cold_validation_requires_every_cached_read_to_miss(
    registration: Registration,
    path: str,
    completed: int,
    outcomes: JsonDict,
    expected: str | None,
) -> None:
    cell = next(
        cell
        for cell in validation_cells(registration, "cold", 1000.0, {})
        if cell.path == path
    )
    record = _record(cell, completed=completed)
    worker = cast("list[JsonDict]", record["workers_measured"])[0]
    cast("JsonDict", worker["outcomes"]).update(outcomes)

    assert validation_failure(record, registration) == expected


def test_mixed_validation_checks_each_model_population(
    registration: Registration,
) -> None:
    cell = next(
        cell
        for cell in validation_cells(
            registration, "primary", 300.0, {"hot": 30.0, "active": 68.0}
        )
        if cell.model == "mixed"
    )

    assert validation_failure(_record(cell), registration) is None


@pytest.mark.parametrize(
    ("family", "rate", "expected"),
    [
        pytest.param("primary", 3000.0, {"hot": 30, "active": 60}, id="primary"),
        pytest.param("cold", 1000.0, {"cold": 10.0}, id="cold"),
        pytest.param("sensitivity", 500.0, {"sensitivity": 30}, id="sensitivity"),
    ],
)
def test_family_durations_follow_the_registered_rule(
    registration: Registration,
    family: str,
    rate: float,
    expected: dict[str, float],
) -> None:
    assert run.family_durations(registration, family, rate) == expected


class _FakeRecorder:
    __slots__ = ("calls", "throughputs")

    def __init__(self, throughputs: dict[str, int]) -> None:
        self.throughputs = throughputs
        self.calls: list[tuple[str, float | None]] = []

    def run(
        self, _replica: object, _registration: Registration, cells: tuple[Cell, ...]
    ) -> list[JsonDict]:
        records = []
        for cell in cells:
            self.calls.append((cell.phase, cell.rate))
            if cell.phase == "probe":
                records.append(_record(cell, completed=self.throughputs[cell.workload]))
                continue
            sufficient = (
                cell.rate is not None and cell.rate <= self.throughputs["limit"]
            )
            completed = (
                cell.identities
                if cell.identities is not None
                else int(cell.window_seconds * cast("float", cell.rate))
            )
            record = _record(cell, completed=completed)
            if not sufficient:
                record["completed_in_window"] = 0
            records.append(record)
        return records


def test_calibration_halves_an_overloaded_family_and_freezes_the_rest(
    registration: Registration,
) -> None:
    recorder = _FakeRecorder(
        {"hot": 40_000, "active": 40_000, "cold": 40_000, "limit": 1_600}
    )

    outcome = run.calibrate(object(), registration, recorder)  # type: ignore[arg-type]

    assert outcome["outcome"] == "validated"
    assert outcome["rates"] == {"primary": 1500, "cold": 1000, "sensitivity": 500}
    selections = cast("JsonDict", outcome["selections"])
    attempts = cast(
        "list[JsonDict]", cast("JsonDict", selections["primary"])["attempts"]
    )
    assert [attempt["rate"] for attempt in attempts] == [3000, 1500]


def test_calibration_reports_an_inconclusive_setup_at_the_attempt_cap(
    registration: Registration,
) -> None:
    recorder = _FakeRecorder(
        {"hot": 40_000, "active": 40_000, "cold": 40_000, "limit": 1}
    )

    outcome = run.calibrate(object(), registration, recorder)  # type: ignore[arg-type]

    assert outcome == {
        "outcome": "inconclusive",
        "reason": "no sustainable primary rate",
        "selections": outcome["selections"],
    }


def test_calibration_stops_when_the_window_cap_cannot_hold_the_floor(
    registration: Registration,
) -> None:
    recorder = _FakeRecorder({"hot": 1_000, "active": 1_000, "cold": 1_000, "limit": 1})

    outcome = run.calibrate(object(), registration, recorder)  # type: ignore[arg-type]

    assert outcome["outcome"] == "inconclusive"
    attempts = cast(
        "list[JsonDict]",
        cast("JsonDict", cast("JsonDict", outcome["selections"])["primary"])[
            "attempts"
        ],
    )
    assert attempts == [
        {"rate": 75, "durations": {"hot": 135, "active": 270}, "failure": "window cap"}
    ]


class _UnhealthyRecorder(_FakeRecorder):
    __slots__ = ("unhealthy_phase",)

    def __init__(self, throughputs: dict[str, int], unhealthy_phase: str) -> None:
        super().__init__(throughputs)
        self.unhealthy_phase = unhealthy_phase

    def run(
        self, replica: object, registration: Registration, cells: tuple[Cell, ...]
    ) -> list[JsonDict]:
        records = super().run(replica, registration, cells)
        if cells[0].phase == self.unhealthy_phase:
            records[0]["healthy"] = False
        return records


@pytest.mark.parametrize("unhealthy_phase", ["probe", "validation"])
def test_calibration_treats_setup_failures_as_inconclusive(
    registration: Registration, unhealthy_phase: str
) -> None:
    recorder = _UnhealthyRecorder(
        {"hot": 40_000, "active": 40_000, "cold": 40_000, "limit": 10_000},
        unhealthy_phase,
    )

    outcome = run.calibrate(object(), registration, recorder)  # type: ignore[arg-type]

    assert outcome["outcome"] == "inconclusive"


def test_freeze_writes_validated_values_and_rejects_others(
    tmp_path: Path, registration: Registration
) -> None:
    config = tmp_path / "config.json"
    config.write_text(_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    report = tmp_path / "calibration.json"
    calibration = {
        "outcome": "validated",
        "rates": _FROZEN_RATES,
        "window_seconds": _FROZEN_WINDOWS,
        "cold_seconds": 10.0,
    }
    environment = {"revision": "abc", "configuration_sha256": registration.digest}
    report.write_text(
        json.dumps({"environment": environment, "calibration": calibration})
    )

    run.freeze(config, report)

    frozen = Registration.load(config)
    assert frozen.frozen
    assert frozen.rate("primary") == 3000
    report.write_text(
        json.dumps(
            {"environment": environment, "calibration": {"outcome": "inconclusive"}}
        )
    )
    with pytest.raises(BenchmarkSetupError, match="only validated"):
        run.freeze(config, report)


_ONLY_SYNC_8 = "cells limited to sync:8"


@pytest.mark.parametrize(
    ("environment", "fields", "exploratory"),
    [
        pytest.param({"revision": "0" * 40}, {}, None, id="revision"),
        pytest.param({}, {"exploratory": _ONLY_SYNC_8}, None, id="limited-report"),
        pytest.param({}, {}, _ONLY_SYNC_8, id="limited-run"),
    ],
)
def test_resume_rejects_another_revision_or_cell_limit(
    tmp_path: Path,
    registration: Registration,
    environment: JsonDict,
    fields: JsonDict,
    exploratory: str | None,
) -> None:
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "phase": "capacity",
                "environment": {**run.environment(registration), **environment},
                "cells": [],
                **fields,
            }
        )
    )

    with pytest.raises(BenchmarkSetupError, match="another phase, cell limit"):
        run.resumed_cells(report, "capacity", registration, exploratory)


def test_resume_reuses_matching_windows_in_order(
    tmp_path: Path, registration: Registration, monkeypatch: pytest.MonkeyPatch
) -> None:
    cells = smoke_cells(registration)[:2]
    reused = _record(cells[0])
    measured: list[Cell] = []

    def measure(_replica: object, _registration: Registration, cell: Cell) -> JsonDict:
        measured.append(cell)
        raise BenchmarkSetupError("deliberate setup failure")

    monkeypatch.setattr(run, "run_window", measure)
    recorder = run.Recorder(tmp_path / "out.json", "smoke", registration, [reused])

    records = recorder.run(object(), registration, cells)  # type: ignore[arg-type]

    assert records[0] is reused
    assert measured == [cells[1]]
    assert records[1]["failure"] == "deliberate setup failure"
    assert (
        json.loads((tmp_path / "out.json").read_text())["cells"][1]["healthy"] is False
    )


def test_throughput_uses_the_slowest_worker_elapsed_time(
    registration: Registration,
) -> None:
    record = _record(probe_cells(registration)[0], completed=500)

    assert run.throughput(record) == pytest.approx(50.0)


@pytest.mark.parametrize("seed", [197, 1970])
def test_key_order_is_a_seeded_permutation(seed: int) -> None:
    keys = key_order(seed, 64)

    assert sorted(keys) == list(range(64))
    assert key_order(seed, 64) == keys


def test_assignment_partitions_requests_round_robin() -> None:
    assignment = Assignment(
        worker=1, workers=3, rate=10.0, requests=10, keys=(5, 6, 7, 8), offset=1
    )

    assert list(assignment.ordinals()) == [1, 4, 7]
    assert [assignment.key(ordinal) for ordinal in assignment.ordinals()] == [7, 6, 5]
    assert assignment.due(100.0, 4) == pytest.approx(100.4)


def _reader(failing: set[int], delay: float) -> Callable[[NonNegativeInt], None]:
    def read(key: NonNegativeInt) -> None:
        time.sleep(delay)
        if key in failing:
            raise LookupError(key)

    return read


def _async_reader(
    failing: set[int], delay: float
) -> Callable[[NonNegativeInt], object]:
    async def read(key: NonNegativeInt) -> None:
        await asyncio.sleep(delay)
        if key in failing:
            raise LookupError(key)

    return read


def _open_loop(
    model: str,
    assignment: Assignment,
    *,
    failing: set[int],
    delay: float,
    concurrency: int,
    outstanding_limit: int,
    drain_seconds: float,
    record: bool,
) -> LoopResult:
    start = time.monotonic() + 0.01
    if model == "sync":
        return open_loop_sync(
            assignment,
            start,
            _reader(failing, delay),
            concurrency=concurrency,
            outstanding_limit=outstanding_limit,
            drain_seconds=drain_seconds,
            record=record,
        )
    return asyncio.run(
        open_loop_async(
            assignment,
            start,
            _async_reader(failing, delay),  # type: ignore[arg-type]
            concurrency=concurrency,
            outstanding_limit=outstanding_limit,
            drain_seconds=drain_seconds,
            record=record,
        )
    )


def _closed_loop(
    model: str, assignment: Assignment, seconds: float, failing: set[int]
) -> LoopResult:
    start = time.monotonic()
    if model == "sync":
        return closed_loop_sync(assignment, start, seconds, _reader(failing, 0.001), 2)
    return asyncio.run(
        closed_loop_async(
            assignment,
            start,
            seconds,
            _async_reader(failing, 0.001),  # type: ignore[arg-type]
            2,
        )
    )


@pytest.mark.parametrize("model", ["sync", "async"])
def test_open_loop_records_errors_and_completions(model: str) -> None:
    assignment = Assignment(
        worker=0, workers=1, rate=200.0, requests=20, keys=tuple(range(20))
    )

    loop = _open_loop(
        model,
        assignment,
        failing={3},
        delay=0.0,
        concurrency=2,
        outstanding_limit=8,
        drain_seconds=1.0,
        record=True,
    )

    assert (loop.offered, loop.completed, loop.errors) == (20, 19, 1)
    assert loop.error_types == {"LookupError": 1}
    assert len(loop.latencies) == 19
    assert cast("JsonDict", loop.summary()["latency"])["sample_count"] == 19


@pytest.mark.parametrize("model", ["sync", "async"])
def test_open_loop_bounds_outstanding_requests(model: str) -> None:
    assignment = Assignment(
        worker=0, workers=1, rate=2_000.0, requests=40, keys=tuple(range(40))
    )

    loop = _open_loop(
        model,
        assignment,
        failing=set(),
        delay=0.05,
        concurrency=1,
        outstanding_limit=2,
        drain_seconds=0.01,
        record=False,
    )

    assert loop.overflow > 0
    assert loop.outstanding_at_end > 0
    assert loop.latencies == []


@pytest.mark.parametrize("model", ["sync", "async"])
def test_closed_loop_stops_at_its_identity_quota(model: str) -> None:
    assignment = Assignment(
        worker=0, workers=2, rate=None, requests=10, keys=tuple(range(10))
    )

    loop = _closed_loop(model, assignment, 5.0, {4})

    assert (loop.offered, loop.completed, loop.errors) == (5, 4, 1)
    assert loop.elapsed < 5.0


def test_checksum_combines_payload_and_revision() -> None:
    assert checksum({"payload": "abc", "revision": 2}) == zlib.crc32(b"abc") ^ 2


def test_checksum_requires_the_document() -> None:
    with pytest.raises(LookupError, match="disappeared"):
        checksum(None)


def test_catalogue_is_deterministic_and_sized(registration: Registration) -> None:
    profile = registration.profile("smoke")
    first = list(catalogue(197, profile, 64))  # type: ignore[arg-type]

    assert first == list(catalogue(197, profile, 64))  # type: ignore[arg-type]
    assert len(first) == 256
    assert all(len(cast("str", document["payload"])) == 4096 for document in first)


def _comparison_records(
    frozen: Registration,
    *,
    shared_pss: float,
    blocks: int,
    phase: str = "confirmation",
) -> list[JsonDict]:
    cells = [
        cell
        for cell in comparison_cells(frozen, phase)
        if cell.block < blocks and cell.workers == 4 and cell.model == "sync"
    ]
    return [
        _record(
            cell,
            pss=shared_pss if cell.path == "shared" else 100.0,
            p99=0.0005 if cell.path != "direct" else 0.002,
            cpu=1.0,
        )
        for cell in cells
    ]


def _report(
    config: Path, phase: str, records: list[JsonDict], revision: str = "a" * 40
) -> JsonDict:
    return {
        "phase": phase,
        "environment": {
            "configuration_sha256": Registration.load(config).digest,
            "revision": revision,
        },
        "cells": records,
    }


def _settings(
    frozen: Registration, blocks: int, *, inference: bool
) -> analysis.InferenceSettings:
    return replace(
        analysis.InferenceSettings.load(frozen, blocks, inference=inference),
        draws=200,
        leave_one_out_draws=50,
    )


@pytest.mark.parametrize(
    ("shared_pss", "outcome"),
    [
        pytest.param(50.0, "pass", id="memory-saving"),
        pytest.param(90.0, "fail", id="insufficient"),
    ],
)
def test_group_memory_gate_uses_the_upper_paired_bound(
    frozen: Registration, shared_pss: float, outcome: str
) -> None:
    records = _comparison_records(frozen, shared_pss=shared_pss, blocks=12)

    comparisons = analysis.compare(
        analysis.paired_blocks(records), _settings(frozen, 12, inference=True)
    )

    memory = next(item for item in comparisons if item.criterion == "group-memory")
    assert memory.outcome == outcome
    assert memory.blocks == 12


def test_a_missing_block_fails_its_comparisons(frozen: Registration) -> None:
    records = _comparison_records(frozen, shared_pss=50.0, blocks=6)
    next(record for record in records if record["path"] == "shared")["healthy"] = False

    comparisons = analysis.compare(
        analysis.paired_blocks(records), _settings(frozen, 6, inference=False)
    )

    assert {item.outcome for item in comparisons} == {"missing"}


def test_unstable_bounds_are_inconclusive(frozen: Registration) -> None:
    records = _comparison_records(frozen, shared_pss=75.0, blocks=12)
    for index, record in enumerate(
        item for item in records if item["path"] == "shared"
    ):
        cast("JsonDict", record["memory"])["steady_group_pss_bytes"] = (
            60.0 if index % 2 else 85.0
        )

    comparisons = analysis.compare(
        analysis.paired_blocks(records), _settings(frozen, 12, inference=True)
    )

    memory = next(item for item in comparisons if item.criterion == "group-memory")
    assert memory.outcome in {"fail", "unstable"}


def test_screening_stops_on_an_observed_failed_condition(frozen: Registration) -> None:
    records = _comparison_records(frozen, shared_pss=90.0, blocks=6)

    decision = analysis.decide(records, frozen, phase="screening", blocks=6)

    assert decision["verdict"] == "stop"
    assert "group-memory" in {
        item["criterion"] for item in cast("list[JsonDict]", decision["failed"])
    }


def test_hit_latency_requires_every_cached_request_to_hit(frozen: Registration) -> None:
    cell = comparison_cells(frozen, "confirmation")[0]
    record = _record(replace(cell, path="shared"), hits=10)

    assert "hit_p95" not in analysis.block_statistics(record)


@pytest.mark.parametrize(
    ("phase", "workload_key", "metric"),
    [
        pytest.param("cold", "cold", "miss_p99", id="cold"),
        pytest.param("active", "active", "lag_p95", id="active"),
    ],
)
def test_block_statistics_select_the_workload_metrics(
    frozen: Registration, phase: str, workload_key: str, metric: str
) -> None:
    cell = next(
        cell
        for cell in comparison_cells(frozen, phase)
        if cell.workload == workload_key and cell.path == "independent"
    )
    record = _record(cell, hits=0, misses=1_000)

    assert metric in analysis.block_statistics(record)


def test_mixed_cells_compare_each_model_population(frozen: Registration) -> None:
    records = [
        _record(cell)
        for cell in comparison_cells(frozen, "active")
        if cell.model == "mixed" and cell.block < 2
    ]

    comparisons = analysis.compare(
        analysis.paired_blocks(records), _settings(frozen, 2, inference=True)
    )

    metrics = {item.metric for item in comparisons}
    assert {"request_p99_sync", "request_p99_async", "lag_p95"} <= metrics


def test_completion_failures_list_unhealthy_and_incomplete_windows(
    frozen: Registration,
) -> None:
    cells = comparison_cells(frozen, "confirmation")[:2]
    failed = _record(cells[0], healthy=False)
    incomplete = _record(cells[1])
    incomplete["offered"] = 2_000

    failures = analysis.completion_failures([failed, incomplete], frozen)

    assert [failure["reason"] for failure in failures] == [
        "deliberate failure",
        "fixed work did not complete",
    ]


def test_analysis_command_describes_and_decides(
    tmp_path: Path, frozen: Registration, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps(frozen.raw))
    report = tmp_path / "report.json"
    records = _comparison_records(frozen, shared_pss=50.0, blocks=2, phase="screening")
    records.append(_record(comparison_cells(frozen, "screening")[0], healthy=False))
    report.write_text(json.dumps(_report(config, "screening", records)))

    analysis.main(
        [str(report), "--config", str(config), "--phase", "screening", "--blocks", "2"]
    )
    decision = json.loads(capsys.readouterr().out)
    analysis.main(
        [
            str(report),
            "--config",
            str(config),
            "--phase",
            "screening",
            "--blocks",
            "2",
            "--describe",
        ]
    )
    description = json.loads(capsys.readouterr().out)

    assert decision["verdict"] == "stop"
    assert any(row["blocks"] == 0 for row in description["descriptive"])


def _without_shared(records: list[JsonDict]) -> list[JsonDict]:
    return [record for record in records if record["path"] != "shared"]


def _first_block(records: list[JsonDict]) -> list[JsonDict]:
    return [record for record in records if record["block"] == 0]


def _without_hits(records: list[JsonDict]) -> list[JsonDict]:
    shared = next(record for record in records if record["path"] == "shared")
    cast("list[JsonDict]", shared["workers_measured"])[0]["outcomes"] = {
        "hits": 0,
        "misses": 0,
        "bypasses": 0,
    }
    return records


@pytest.mark.parametrize(
    "incomplete",
    [
        pytest.param(_without_shared, id="missing-path"),
        pytest.param(_first_block, id="missing-block"),
        pytest.param(_without_hits, id="missing-metric"),
    ],
)
def test_incomplete_pairs_are_missing(
    frozen: Registration,
    incomplete: Callable[[list[JsonDict]], list[JsonDict]],
) -> None:
    records = incomplete(_comparison_records(frozen, shared_pss=50.0, blocks=2))

    comparisons = analysis.compare(
        analysis.paired_blocks(records), _settings(frozen, 2, inference=False)
    )

    missing = {item.criterion for item in comparisons if item.outcome == "missing"}
    assert "hit-p95" in missing


@pytest.mark.parametrize(
    ("shared_pss", "verdict"),
    [
        pytest.param(50.0, "promote", id="promote"),
        pytest.param(90.0, "defer", id="defer"),
    ],
)
def test_confirmation_decisions_require_every_bound(
    frozen: Registration, shared_pss: float, verdict: str
) -> None:
    raw = copy.deepcopy(frozen.raw)
    cast("JsonDict", raw["inference"]).update({"draws": 200, "leave_one_out_draws": 50})
    small = replace(frozen, raw=raw)
    records = _comparison_records(small, shared_pss=shared_pss, blocks=4)

    decision = analysis.decide(records, small, phase="confirmation", blocks=4)

    assert decision["verdict"] == verdict


def test_processor_name_falls_back_without_a_model_line() -> None:
    assert run.processor_name("model name\t: Example CPU\n") == "Example CPU"
    assert isinstance(run.processor_name("vendor_id : none\n"), str)


def test_environment_requires_git(
    registration: Registration, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    with pytest.raises(BenchmarkSetupError, match="git is required"):
        run.environment(registration)


@pytest.mark.parametrize(
    ("fields", "exploratory"),
    [
        pytest.param({}, None, id="registered"),
        pytest.param({"exploratory": _ONLY_SYNC_8}, _ONLY_SYNC_8, id="same-limit"),
    ],
)
def test_resume_accepts_the_same_revision_and_cell_limit(
    tmp_path: Path,
    registration: Registration,
    fields: JsonDict,
    exploratory: str | None,
) -> None:
    report = tmp_path / "report.json"
    cells = [_record(smoke_cells(registration)[0])]
    report.write_text(
        json.dumps(
            {
                "phase": "capacity",
                "environment": run.environment(registration),
                "cells": cells,
                **fields,
            }
        )
    )

    assert run.resumed_cells(report, "capacity", registration, exploratory) == cells


def test_freeze_command_updates_the_registration(
    tmp_path: Path, registration: Registration
) -> None:
    config = tmp_path / "config.json"
    config.write_text(_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    report = tmp_path / "calibration.json"
    report.write_text(
        json.dumps(
            {
                "environment": {"revision": "abc", "configuration_sha256": "def"},
                "calibration": {
                    "outcome": "validated",
                    "rates": _FROZEN_RATES,
                    "window_seconds": _FROZEN_WINDOWS,
                    "cold_seconds": 10.0,
                },
            }
        )
    )

    run.main(["--freeze", str(report), "--config", str(config)])

    assert Registration.load(config).frozen
    assert registration.digest != Registration.load(config).digest


@pytest.mark.parametrize("model", ["sync", "async"])
def test_closed_loop_ends_at_its_window(model: str) -> None:
    assignment = Assignment(
        worker=0, workers=1, rate=None, requests=10**6, keys=tuple(range(10))
    )

    loop = _closed_loop(model, assignment, 0.05, set())

    assert loop.completed > 0
    assert loop.elapsed == pytest.approx(0.05, abs=0.05)


class _RecordingCollection:
    __slots__ = ("batches",)

    def __init__(self) -> None:
        self.batches: list[int] = []

    def insert_many(self, documents: list[BsonDict]) -> None:
        self.batches.append(len(documents))


class _RecordingClient:
    __slots__ = ("collection",)

    def __init__(self) -> None:
        self.collection = _RecordingCollection()

    @staticmethod
    def drop_database(_name: str) -> None:
        return None

    def __getitem__(self, _name: str) -> dict[str, _RecordingCollection]:
        return {"catalogue": self.collection}


@pytest.mark.parametrize(
    ("documents", "batches"),
    [
        pytest.param(1024, [512, 512], id="whole-batches"),
        pytest.param(600, [512, 88], id="tail"),
    ],
)
def test_seeding_inserts_bounded_batches(documents: int, batches: list[int]) -> None:
    client = _RecordingClient()

    summary = seed_catalogue(
        client,  # type: ignore[arg-type]
        database="research",
        collection="catalogue",
        seed=197,
        profile={"documents": documents, "payload_bytes": 64, "read": "find_one"},
        categories=4,
    )

    assert client.collection.batches == batches
    assert summary["documents"] == documents


def test_reused_probes_keep_only_healthy_probe_windows(
    tmp_path: Path, registration: Registration
) -> None:
    probe = probe_cells(registration)[0]
    validation = validation_cells(
        registration, "primary", 100.0, {"hot": 30.0, "active": 60.0}
    )[0]
    report = tmp_path / "calibration.json"
    healthy = _record(probe)
    report.write_text(
        json.dumps(
            {
                "phase": "calibration",
                "cells": [healthy, _record(probe, healthy=False), _record(validation)],
            }
        )
    )

    assert run.reused_probes(report) == [healthy]
    report.write_text(json.dumps({"phase": "smoke", "cells": [healthy]}))
    with pytest.raises(BenchmarkSetupError, match="healthy probes"):
        run.reused_probes(report)


def _checksum(value: object) -> int:
    return zlib.crc32(json.dumps(value, default=list, sort_keys=True).encode())


def _v4_validation(family: str) -> Callable[[Registration], tuple[Cell, ...]]:
    def plan(v4: Registration) -> tuple[Cell, ...]:
        rate = v4.rate(family)
        return validation_cells(
            v4, family, rate, run.family_durations(v4, family, rate)
        )

    return plan


def _v4_phase(phase: str) -> Callable[[Registration], tuple[Cell, ...]]:
    def plan(v4: Registration) -> tuple[Cell, ...]:
        return run.planned(v4, phase, v4.paths)

    return plan


@pytest.mark.parametrize(
    ("plan", "expected"),
    [
        pytest.param(
            _v4_phase("screening"),
            935_413_582,
            id="screening",
        ),
        pytest.param(
            _v4_phase("confirmation"),
            899_046_424,
            id="confirmation",
        ),
        pytest.param(
            _v4_phase("capacity"),
            3_320_248_846,
            id="capacity",
        ),
        pytest.param(
            _v4_phase("active"),
            2_216_856_171,
            id="active",
        ),
        pytest.param(
            _v4_phase("cold"),
            2_255_952_015,
            id="cold",
        ),
        pytest.param(
            _v4_phase("sensitivity"),
            2_527_074_307,
            id="sensitivity",
        ),
        pytest.param(
            probe_cells,
            2_502_144_019,
            id="probe",
        ),
        pytest.param(
            smoke_cells,
            3_139_303_506,
            id="smoke",
        ),
        pytest.param(
            _v4_validation("primary"),
            503_062_652,
            id="validation-primary",
        ),
        pytest.param(
            _v4_validation("cold"),
            4_195_228_211,
            id="validation-cold",
        ),
        pytest.param(
            _v4_validation("sensitivity"),
            1_434_493_908,
            id="validation-sensitivity",
        ),
    ],
)
def test_v4_registration_plans_the_same_cells(
    plan: Callable[[Registration], tuple[Cell, ...]], expected: int
) -> None:
    v4 = Registration.load(_CONFIG)

    assert f"SHA-256 `{v4.digest}`" in _V4_COMPANION.read_text(encoding="utf-8")
    assert _checksum([asdict(cell) for cell in plan(v4)]) == expected


def test_v4_freezing_keeps_its_frozen_block_layout(
    tmp_path: Path, registration: Registration
) -> None:
    recorder = _FakeRecorder(
        {"hot": 40_000, "active": 40_000, "cold": 40_000, "limit": 10_000}
    )
    outcome = run.calibrate(object(), registration, recorder)  # type: ignore[arg-type]
    config = tmp_path / "config.json"
    config.write_bytes(_CONFIG.read_bytes())
    report = tmp_path / "calibration.json"
    report.write_text(json.dumps({"calibration": outcome}))

    run.freeze(config, report)

    v4 = Registration.load(_CONFIG)
    layout = {
        key: list(cast("JsonDict", value))
        for key, value in v4.section("frozen").items()
    }
    refrozen = Registration.load(config).section("frozen")
    assert {key: list(cast("JsonDict", value)) for key, value in refrozen.items()} == (
        layout
    )
    frozen = v4.section("frozen")
    summary = cast("JsonDict", frozen["calibration_summary"])
    report.write_text(
        json.dumps(
            {
                "calibration": {
                    "outcome": "validated",
                    "rates": frozen["rates"],
                    "window_seconds": frozen["window_seconds"],
                    "cold_seconds": summary["cold_seconds"],
                }
            }
        )
    )
    run.freeze(config, report)
    assert config.read_bytes() == _CONFIG.read_bytes()


def test_registered_steady_phase_plans_only_its_cells(
    concurrent_frozen: Registration,
) -> None:
    cells = run.planned(concurrent_frozen, "steady", concurrent_frozen.paths)

    assert len(cells) == 12 * len(_CONCURRENT_CELLS)
    for block in range(12):
        assert {
            (cell.workload, cell.model, cell.workers, cell.path)
            for cell in cells
            if cell.block == block
        } == _CONCURRENT_CELLS
    assert {(cell.rate, cell.window_seconds) for cell in cells} == {
        (_CONCURRENT_RATE, 60)
    }
    assert [cell.path for cell in cells[:2]] == ["direct", "independent"]
    assert [cell.path for cell in cells[4:6]] == ["independent", "direct"]


def _assign(raw: JsonDict, keys: tuple[str, ...], value: object) -> None:
    target = raw
    for key in keys[:-1]:
        target = cast("JsonDict", target[key])
    target[keys[-1]] = value


@pytest.mark.parametrize(
    ("keys", "value", "phase", "message"),
    [
        pytest.param(
            ("status",), "frozen", "screening", "no screening phase", id="unknown"
        ),
        pytest.param(
            ("status",), "frozen", "smoke", "smoke phase has no blocks", id="smoke"
        ),
        pytest.param(
            ("phases", "soak"),
            {"blocks": 1},
            "soak",
            "soak phase lists no cells",
            id="without-cells",
        ),
        pytest.param(
            ("phases", "steady", "cells"),
            [],
            "steady",
            "steady phase lists no cells",
            id="empty-cells",
        ),
        pytest.param(
            ("phases", "steady", "cells"),
            [["active", "async"]],
            "steady",
            "malformed cell",
            id="short-cell",
        ),
        pytest.param(
            ("phases", "steady", "cells"),
            [["warm", "async", 1]],
            "steady",
            "malformed cell",
            id="unknown-workload",
        ),
        pytest.param(
            ("phases", "steady", "cells"),
            [["active", "async", 0]],
            "steady",
            "malformed cell",
            id="no-workers",
        ),
        pytest.param(
            ("phases", "steady", "cells"),
            [["active", "async", True]],
            "steady",
            "malformed cell",
            id="boolean-workers",
        ),
        pytest.param(
            ("phases", "steady", "cells"),
            [["hot", "async", 1]],
            "steady",
            "no calibration family covers hot cells",
            id="uncalibrated",
        ),
        pytest.param(
            ("phases", "steady", "cells"),
            [["active", "async", 4], ["active", "async", 4]],
            "steady",
            "steady phase repeats a cell",
            id="repeated-cell",
        ),
    ],
)
def test_unregistered_phases_and_malformed_cells_are_configuration_errors(
    concurrent_frozen: Registration,
    keys: tuple[str, ...],
    value: object,
    phase: str,
    message: str,
) -> None:
    raw = copy.deepcopy(concurrent_frozen.raw)
    _assign(raw, keys, value)

    with pytest.raises(BenchmarkConfigurationError, match=message):
        run.planned(replace(concurrent_frozen, raw=raw), phase, BASELINES)


def test_an_unregistered_phase_fails_before_writing_a_report(
    tmp_path: Path, concurrent_frozen: Registration
) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps(concurrent_frozen.raw))
    output = tmp_path / "report.json"

    with pytest.raises(BenchmarkConfigurationError, match="no capacity phase"):
        run.main(
            [
                "--phase",
                "capacity",
                "--config",
                str(config),
                "--output",
                str(output),
            ]
        )

    assert not output.exists()


def test_registered_family_probes_reads_and_validates_mixed_cells(
    concurrent: Registration,
) -> None:
    durations = run.family_durations(concurrent, "steady", _CONCURRENT_RATE)
    probes = probe_cells(concurrent)
    validations = validation_cells(concurrent, "steady", _CONCURRENT_RATE, durations)

    assert durations == {"active": 60}
    assert {(cell.workload, cell.loop) for cell in probes} == {("hot", "closed")}
    assert {(cell.workload, cell.loop) for cell in validations} == {("active", "open")}
    for cells in (probes, validations):
        assert {
            ("active", cell.model, cell.workers, cell.path) for cell in cells
        } == _CONCURRENT_CELLS


def test_registered_family_freezes_only_its_rate_and_window(
    tmp_path: Path, concurrent: Registration
) -> None:
    recorder = _FakeRecorder({"hot": 20_000, "limit": 10_000})
    outcome = run.calibrate(object(), concurrent, recorder)  # type: ignore[arg-type]
    config = tmp_path / "config.json"
    config.write_text(json.dumps(concurrent.raw, indent=2))
    report = tmp_path / "calibration.json"
    report.write_text(json.dumps({"calibration": outcome}))

    run.freeze(config, report)

    frozen = Registration.load(config)
    assert frozen.raw["status"] == "frozen"
    assert frozen.section("frozen") == {
        "rates": {"steady": 1500},
        "window_seconds": {"active": 60},
        "calibration_summary": {},
    }
    assert {cell.rate for cell in run.planned(frozen, "steady", frozen.paths)} == {1500}


def test_open_loop_writes_follow_the_registered_read_share(
    concurrent_frozen: Registration,
) -> None:
    cell = comparison_cells(concurrent_frozen, "steady")[1]

    workload = window._workload(concurrent_frozen, cell)

    updates = _CONCURRENT_RATE * 60 // 20
    assert write_count(concurrent_frozen, cell) == updates
    assert len(workload.writes) == updates
    assert workload.expected_invalidations == updates
    assert len(workload.keys) == concurrent_frozen.hot_keys
    assert {target for _offset, target in workload.writes} == set(workload.keys)


def test_closed_loop_windows_cannot_derive_a_write_count(
    concurrent_frozen: Registration,
) -> None:
    cell = replace(
        comparison_cells(concurrent_frozen, "steady")[0], loop="closed", rate=None
    )

    with pytest.raises(BenchmarkConfigurationError, match="open-loop rate"):
        write_count(concurrent_frozen, cell)


@pytest.mark.parametrize(
    ("keys", "value", "message"),
    [
        pytest.param(
            ("active", "updates"), 200, "both updates and reads_per_write", id="both"
        ),
        pytest.param(
            ("active", "write_keys"), "catalogue", "only the hot set", id="targets"
        ),
        pytest.param(
            ("active", "reads_per_write"), 0, "reads_per_write", id="read-share"
        ),
        pytest.param(("hot_keys",), True, "hot_keys", id="hot-keys"),
        pytest.param(
            ("key_assignment",), "random", "partitioned or shared", id="assignment"
        ),
        pytest.param(("paths",), ["direct", "redis"], "paths", id="unknown-path"),
        pytest.param(("paths",), [], "paths", id="no-paths"),
        pytest.param(
            ("paths",), ["direct", "direct"], "repeat a path", id="repeated-path"
        ),
        pytest.param(
            ("calibration", "families", "steady", "cells"),
            [["active", "async", 1], ["active", "async", 1]],
            "steady family repeats a cell",
            id="repeated-family-cell",
        ),
        pytest.param(("calibration", "families"), {}, "no families", id="no-families"),
        pytest.param(
            ("calibration", "families", "steady"),
            {"cells": [["active", "async", 1]]},
            "steady family is malformed",
            id="malformed-family",
        ),
        pytest.param(
            ("calibration", "families", "steady", "cells"),
            [],
            "steady family lists no cells",
            id="empty-family",
        ),
        pytest.param(
            ("calibration", "families", "steady"),
            [["active", "async", 1]],
            "read-only probes",
            id="active-probes",
        ),
        pytest.param(
            ("calibration", "families", "steady", "probe_workload"),
            "active",
            "read-only probes",
            id="active-probe-workload",
        ),
        pytest.param(
            ("calibration", "probe_windows"), 0, "probe_windows", id="no-probes"
        ),
        pytest.param(
            ("calibration", "validation_repetitions"),
            0,
            "validation_repetitions",
            id="no-validation",
        ),
        pytest.param(
            ("calibration", "rate_attempts"), 0, "rate_attempts", id="no-attempts"
        ),
        pytest.param(
            ("phases", "steady", "blocks"), 0, "steady phase blocks", id="no-blocks"
        ),
        pytest.param(
            ("inference", "lag_event_floor"), 0, "lag_event_floor", id="no-lag-floor"
        ),
    ],
)
def test_unsupported_registration_settings_are_rejected(
    concurrent: Registration, keys: tuple[str, ...], value: object, message: str
) -> None:
    raw = copy.deepcopy(concurrent.raw)
    _assign(raw, keys, value)

    with pytest.raises(BenchmarkConfigurationError, match=message):
        Registration(raw, concurrent.digest)


@given(
    workers=st.integers(min_value=1, max_value=8),
    hot_keys=st.integers(min_value=1, max_value=64),
    seed=st.integers(min_value=0, max_value=2**32),
)
def test_shared_assignment_gives_every_worker_the_whole_hot_set(
    workers: int, hot_keys: int, seed: int
) -> None:
    hot = key_order(seed, hot_keys)
    rate = 100.0
    requests = workers * hot_keys
    shared = [
        Assignment(
            worker=worker,
            workers=workers,
            rate=rate,
            requests=requests,
            keys=worker_keys(seed, worker, hot),
            key_assignment="shared",
        )
        for worker in range(workers)
    ]
    partitioned = [
        replace(assignment, keys=hot, key_assignment="partitioned")
        for assignment in shared
    ]

    for assignment in shared:
        assert {assignment.key(ordinal) for ordinal in assignment.ordinals()} == set(
            hot
        )
    schedules = [
        sorted(
            assignment.due(0.0, ordinal)
            for assignment in assignments
            for ordinal in assignment.ordinals()
        )
        for assignments in (shared, partitioned)
    ]
    assert (
        schedules[0] == schedules[1] == [ordinal / rate for ordinal in range(requests)]
    )


def _describable(
    registration: Registration, *, lag_events: int, bypasses: int
) -> list[JsonDict]:
    records: list[JsonDict] = []
    for cell in comparison_cells(registration, "steady"):
        record = _record(
            cell,
            p99=0.002 if cell.path == "direct" else 0.001,
            cpu=1.0 + cell.block / 10,
            hits=0 if cell.path == "direct" else 900,
            misses=0 if cell.path == "direct" else 100,
        )
        worker = cast("list[JsonDict]", record["workers_measured"])[0]
        cast("JsonDict", worker["outcomes"])["bypass_reasons"] = (
            {} if cell.path == "direct" else {"stream_unavailable": bypasses}
        )
        worker["lag"] = {"lag_windows": [[0.02] * lag_events]}
        record["server_cpu_seconds"] = 2.0 if cell.path == "direct" else 0.5
        records.append(record)
    return records


def _workers(row: JsonDict) -> int:
    return cast("analysis.CellKey", row["cell"])[3]


@pytest.fixture
def described(concurrent_frozen: Registration) -> Registration:
    raw = copy.deepcopy(concurrent_frozen.raw)
    cast("JsonDict", raw["inference"])["draws"] = 200
    _assign(raw, ("phases", "steady", "blocks"), 2)
    return replace(concurrent_frozen, raw=raw)


@pytest.mark.parametrize(
    ("lag_events", "claimed"),
    [
        pytest.param(250, True, id="lag-floor-met"),
        pytest.param(20, False, id="lag-below-floor"),
    ],
)
def test_descriptive_analysis_reports_intervals_counts_and_claimed_lag(
    described: Registration, lag_events: int, claimed: bool
) -> None:
    records = _describable(described, lag_events=lag_events, bypasses=2_500)

    report = analysis.describe_phase(records, described, phase="steady", blocks=2)

    comparisons = cast("list[JsonDict]", report["comparisons"])
    assert {item["measure"] for item in comparisons} == set(
        cast("list[str]", described.section("analysis")["measures"])
    )
    for comparison in comparisons:
        assert comparison["pairs"] == 2
        for estimand in ("ratio", "delta"):
            interval = cast("JsonDict", comparison[estimand])
            assert (
                cast("float", interval["lower"])
                <= cast("float", interval["point_estimate"])
                <= cast("float", interval["upper"])
            )
    p99 = next(
        item
        for item in comparisons
        if item["measure"] == "request_p99" and _workers(item) == 4
    )
    assert cast("JsonDict", p99["ratio"])["point_estimate"] == pytest.approx(0.5)
    rows = {
        (_workers(row), row["path"]): row
        for row in cast("list[JsonDict]", report["paths"])
    }
    cached = rows[4, "independent"]
    assert cast("JsonDict", cached["bypass_stream_unavailable"])["max"] == 2_500
    assert cast("JsonDict", cached["hits"])["mean"] == 900
    assert not any("bypass" in key for key in rows[4, "direct"])
    assert ("lag_p95" in cached) is claimed
    assert "lag_p50" not in rows[4, "direct"]
    assert len(cast("list[JsonDict]", report["lag_unclaimed"])) == (
        0 if claimed else 2 * 2
    )
    assert report["excluded"] == []


def _fail_setup(record: JsonDict) -> None:
    record.update(healthy=False, failure="deliberate failure")


def _lose_stream(record: JsonDict) -> None:
    cast("list[JsonDict]", record["workers_measured"])[0]["streams"] = 0


def _overload(record: JsonDict) -> None:
    record["completed_in_window"] = 0


@pytest.mark.parametrize(
    ("alter", "reason"),
    [
        pytest.param(_fail_setup, "deliberate failure", id="unhealthy"),
        pytest.param(_lose_stream, "stream openings differ", id="streams"),
        pytest.param(_overload, "registered fraction", id="overloaded"),
    ],
)
def test_descriptive_analysis_retains_excluded_windows_with_their_reason(
    described: Registration, alter: Callable[[JsonDict], None], reason: str
) -> None:
    records = _describable(described, lag_events=250, bypasses=0)
    for record in records:
        if record["path"] == "independent" and record["workers"] == 4:
            alter(record)

    report = analysis.describe_phase(records, described, phase="steady", blocks=2)

    excluded = cast("list[JsonDict]", report["excluded"])
    assert [(item["path"], item["block"]) for item in excluded] == [
        ("independent", 0),
        ("independent", 1),
    ]
    assert reason in str(excluded[0]["reason"])
    unpaired = [
        item
        for item in cast("list[JsonDict]", report["comparisons"])
        if _workers(item) == 4
    ]
    assert {item["pairs"] for item in unpaired} == {0}
    assert not any("ratio" in item for item in unpaired)


def test_analysis_command_describes_an_ungated_registration(
    tmp_path: Path, described: Registration, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps(described.raw))
    report = tmp_path / "report.json"
    records = _describable(described, lag_events=250, bypasses=0)
    report.write_text(json.dumps(_report(config, "steady", records)))

    analysis.main(
        [str(report), "--config", str(config), "--phase", "steady", "--blocks", "2"]
    )

    output = json.loads(capsys.readouterr().out)
    assert output["phase"] == "steady"
    assert "verdict" not in output
    assert len(output["comparisons"]) == 2 * len(
        cast("list[str]", described.section("analysis")["measures"])
    )


@pytest.mark.parametrize(
    ("phase", "blocks", "shared_pss", "expected"),
    [
        pytest.param(
            "screening",
            6,
            90.0,
            1_732_398_015,
            id="screening-stop",
        ),
        pytest.param(
            "confirmation",
            4,
            50.0,
            1_137_233_933,
            id="confirmation-promote",
        ),
        pytest.param(
            "confirmation",
            4,
            90.0,
            1_877_843_654,
            id="confirmation-defer",
        ),
    ],
)
def test_gated_decisions_are_unchanged(
    frozen: Registration, phase: str, blocks: int, shared_pss: float, expected: int
) -> None:
    raw = copy.deepcopy(frozen.raw)
    cast("JsonDict", raw["inference"]).update({"draws": 200, "leave_one_out_draws": 50})
    small = replace(frozen, raw=raw)
    records = _comparison_records(small, shared_pss=shared_pss, blocks=blocks)

    decision = analysis.decide(records, small, phase=phase, blocks=blocks)

    assert _checksum(decision) == expected


def test_hot_set_limits_only_warm_workloads(concurrent_frozen: Registration) -> None:
    steady = comparison_cells(concurrent_frozen, "steady")[0]
    cold = replace(steady, workload="cold", identities=100)

    assert len(window._workload(concurrent_frozen, cold).keys) == 16_384
    assert len(window._workload(concurrent_frozen, steady).keys) == 1_024


def _cold_specs(
    registration: Registration, identities: int, path: PathKind = "independent"
) -> tuple[WorkerSpec, ...]:
    raw = copy.deepcopy(registration.raw)
    cast("JsonDict", cast("JsonDict", raw["profiles"])["primary"])["documents"] = 256
    resized = replace(registration, raw=raw)
    cell = replace(
        comparison_cells(resized, "steady")[0],
        workload="cold",
        workers=2,
        path=path,
        identities=identities,
    )
    workload = window._workload(resized, cell)
    return tuple(
        window._spec(
            resized, cell, workload, "mongodb://unused", index=index, attachment=None
        )
        for index in range(cell.workers)
    )


def _with_assignment(registration: Registration, assignment: str) -> Registration:
    raw = copy.deepcopy(registration.raw)
    raw["key_assignment"] = assignment
    return replace(registration, raw=raw)


def _measured(spec: WorkerSpec) -> frozenset[int]:
    assignment = spec.assignment(warmup=False)
    return frozenset(assignment.key(ordinal) for ordinal in assignment.ordinals())


def test_cold_workers_on_one_owner_warm_a_key_that_no_worker_measures(
    concurrent_frozen: Registration,
) -> None:
    one_free_key = 255

    specs = _cold_specs(
        _with_assignment(concurrent_frozen, "partitioned"), one_free_key, "shared"
    )

    measured = frozenset().union(*map(_measured, specs))
    assert all(spec.warm_key is not None for spec in specs)
    assert not {spec.warm_key for spec in specs} & measured


@pytest.mark.parametrize(
    ("assignment", "identities", "path"),
    [
        pytest.param("shared", 200, "independent", id="shared-keys"),
        pytest.param("partitioned", 200, "independent", id="partitioned-keys"),
        pytest.param("partitioned", 256, "independent", id="every-document-read"),
        pytest.param("partitioned", 256, "direct", id="every-document-direct"),
    ],
)
def test_private_cold_workers_warm_a_key_outside_their_own_identities(
    concurrent_frozen: Registration, assignment: str, identities: int, path: PathKind
) -> None:
    specs = _cold_specs(
        _with_assignment(concurrent_frozen, assignment), identities, path
    )

    assert all(
        spec.warm_key is not None and spec.warm_key not in _measured(spec)
        for spec in specs
    )


@pytest.mark.parametrize(
    ("identities", "message"),
    [
        pytest.param(512, "no unread key", id="every-key-read"),
        pytest.param(600, "repeat a worker's keys", id="keys-repeat"),
    ],
)
def test_cold_identities_must_stay_distinct_and_leave_a_key_to_warm(
    concurrent_frozen: Registration, identities: int, message: str
) -> None:
    with pytest.raises(BenchmarkConfigurationError, match=message):
        _cold_specs(concurrent_frozen, identities=identities)


def _foreign_registration(first: JsonDict, _second: JsonDict) -> None:
    cast("JsonDict", first["environment"])["configuration_sha256"] = "0" * 64


def _foreign_phase(_first: JsonDict, second: JsonDict) -> None:
    second["phase"] = "smoke"


def _foreign_revision(_first: JsonDict, second: JsonDict) -> None:
    cast("JsonDict", second["environment"])["revision"] = "b" * 40


def _foreign_window(_first: JsonDict, second: JsonDict) -> None:
    cast("list[JsonDict]", second["cells"])[0]["phase"] = "validation"


def _repeated_windows(first: JsonDict, second: JsonDict) -> None:
    second["cells"] = first["cells"]


def _failed_window_rerun(first: JsonDict, second: JsonDict) -> None:
    window = cast("list[JsonDict]", first["cells"])[0]
    cast("list[JsonDict]", second["cells"]).append(
        {**window, "healthy": False, "failure": "deliberate failure"}
    )


def _exploratory_report(_first: JsonDict, second: JsonDict) -> None:
    second["exploratory"] = _ONLY_SYNC_8


@pytest.mark.parametrize(
    ("alter", "message"),
    [
        pytest.param(_foreign_registration, "another registration", id="registration"),
        pytest.param(_foreign_phase, "holds the smoke phase", id="phase"),
        pytest.param(_foreign_revision, "different revisions", id="revision"),
        pytest.param(_foreign_window, "outside the steady phase", id="window"),
        pytest.param(_repeated_windows, "duplicate", id="duplicate"),
        pytest.param(_failed_window_rerun, "duplicate", id="failed-rerun"),
        pytest.param(_exploratory_report, "is exploratory", id="exploratory"),
    ],
)
def test_analysis_rejects_mismatched_or_repeated_evidence(
    tmp_path: Path,
    described: Registration,
    alter: Callable[[JsonDict, JsonDict], None],
    message: str,
) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps(described.raw))
    records = _describable(described, lag_events=250, bypasses=0)
    reports = [
        _report(
            config,
            "steady",
            [record for record in records if record["block"] == block],
        )
        for block in (0, 1)
    ]
    alter(*reports)
    paths = [tmp_path / f"steady-{block}.json" for block in (0, 1)]
    for path, report in zip(paths, reports, strict=True):
        path.write_text(json.dumps(report))

    with pytest.raises(BenchmarkSetupError, match=message):
        analysis.main(
            [
                *map(str, paths),
                "--config",
                str(config),
                "--phase",
                "steady",
                "--blocks",
                "2",
            ]
        )


def test_descriptive_analysis_rejects_a_failed_window_and_its_rerun(
    described: Registration,
) -> None:
    records = _describable(described, lag_events=250, bypasses=0)
    records.append({**records[0], "healthy": False, "failure": "deliberate failure"})

    with pytest.raises(BenchmarkSetupError, match="duplicate window"):
        analysis.describe_phase(records, described, phase="steady", blocks=2)


def test_capacity_analysis_keeps_each_concurrency_level(frozen: Registration) -> None:
    records = [_record(cell) for cell in capacity_cells(frozen) if cell.block == 0]

    rows = analysis.descriptive(records)

    keys = {cast("tuple[str, str, str, int, int]", row["cell"]) for row in rows}
    assert {key[4] for key in keys} == {1, 4, 16}
    assert len(rows) == len(records)


def test_shared_key_assignment_rejects_cold_windows_on_the_shared_path(
    registration: Registration,
) -> None:
    raw = copy.deepcopy(registration.raw)
    raw["key_assignment"] = "shared"

    with pytest.raises(BenchmarkConfigurationError, match="all-miss cold windows"):
        Registration(raw, registration.digest)


def test_shared_key_assignment_allows_the_shared_path_without_cold_windows(
    concurrent: Registration,
) -> None:
    raw = copy.deepcopy(concurrent.raw)
    raw["paths"] = ["direct", "independent", "shared"]

    assert "shared" in Registration(raw, concurrent.digest).paths


def test_mixed_windows_describe_pooled_request_percentiles(
    frozen: Registration,
) -> None:
    cell = next(
        cell for cell in comparison_cells(frozen, "active") if cell.model == "mixed"
    )

    statistics = analysis.window_statistics(_record(cell), lag_floor=1)

    assert {
        "request_p50",
        "request_p95",
        "request_p99",
        "request_p99_sync",
        "request_p99_async",
    } <= statistics.keys()


@pytest.mark.parametrize(
    ("owner", "expected"),
    [
        pytest.param({}, None, id="steady-owner"),
        pytest.param(
            {"commands": {"stream:opened": 1}},
            "the shared owner's stream was unhealthy or reopened",
            id="reopened",
        ),
        pytest.param(
            {"health": "reconnecting"},
            "the shared owner's stream was unhealthy or reopened",
            id="unhealthy",
        ),
    ],
)
def test_descriptive_analysis_checks_the_shared_owner_stream(
    frozen: Registration, owner: JsonDict, expected: str | None
) -> None:
    cell = next(
        cell
        for cell in comparison_cells(frozen, "confirmation")
        if cell.path == "shared"
    )
    record = _record(cell)
    cast("JsonDict", record["owner"]).update(owner)

    assert analysis.exclusion_reason(record, frozen) == expected


def test_descriptive_analysis_requires_the_registered_block_count(
    described: Registration,
) -> None:
    records = _describable(described, lag_events=250, bypasses=0)

    with pytest.raises(BenchmarkConfigurationError, match="registers 2 blocks"):
        analysis.describe_phase(records, described, phase="steady", blocks=1)


def test_a_hot_set_requires_hot_write_targets(concurrent: Registration) -> None:
    raw = copy.deepcopy(concurrent.raw)
    del cast("JsonDict", raw["active"])["write_keys"]

    with pytest.raises(BenchmarkConfigurationError, match="needs active write_keys"):
        Registration(raw, concurrent.digest)


def test_descriptive_analysis_requires_one_stream_per_cached_worker(
    described: Registration,
) -> None:
    record = next(
        record
        for record in _describable(described, lag_events=250, bypasses=0)
        if record["path"] == "independent" and record["workers"] == 4
    )
    worker = cast("list[JsonDict]", record["workers_measured"])[0]
    record["workers_measured"] = [{**worker, "streams": 2}, {**worker, "streams": 0}]

    assert analysis.exclusion_reason(record, described) == (
        "observed stream openings differ from the registered count"
    )


@pytest.mark.parametrize(
    "order",
    [
        pytest.param(("primary", "cold", "sensitivity"), id="registered-order"),
        pytest.param(("cold", "sensitivity", "primary"), id="primary-last"),
    ],
)
def test_primary_rate_caps_other_families_in_any_declared_order(
    registration: Registration, order: tuple[str, ...]
) -> None:
    raw = copy.deepcopy(registration.raw)
    declared = cast("JsonDict", cast("JsonDict", raw["calibration"])["families"])
    cast("JsonDict", raw["calibration"])["families"] = {
        name: declared[name] for name in order
    }
    recorder = _FakeRecorder(
        {"hot": 10_000, "active": 10_000, "cold": 40_000, "limit": 10_000}
    )

    outcome = run.calibrate(object(), replace(registration, raw=raw), recorder)  # type: ignore[arg-type]

    assert outcome["rates"] == {"primary": 750, "cold": 750, "sensitivity": 500}


def test_descriptive_registrations_require_a_lag_floor(
    concurrent: Registration,
) -> None:
    raw = copy.deepcopy(concurrent.raw)
    del cast("JsonDict", raw["inference"])["lag_event_floor"]

    with pytest.raises(BenchmarkConfigurationError, match="lag_event_floor"):
        Registration(raw, concurrent.digest)
