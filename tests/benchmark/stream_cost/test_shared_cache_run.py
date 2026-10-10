from __future__ import annotations

import asyncio
import copy
import json
import shutil
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from benchmarks.stream_cost.errors import (
    BenchmarkConfigurationError,
    BenchmarkSetupError,
)
from benchmarks.stream_cost.shared_cache import analysis, run
from benchmarks.stream_cost.shared_cache.dataset import (
    catalogue,
    checksum,
    seed_catalogue,
)
from benchmarks.stream_cost.shared_cache.protocol import (
    BASELINES,
    PATHS,
    Registration,
    capacity_cells,
    comparison_cells,
    path_order,
    probe_cells,
    smoke_cells,
    validation_cells,
    window_for,
)
from benchmarks.stream_cost.shared_cache.workload import (
    Assignment,
    LoopResult,
    closed_loop_async,
    closed_loop_sync,
    key_order,
    open_loop_async,
    open_loop_sync,
)
from client_query_cache._types import BsonDict, JsonDict, NonNegativeInt

if TYPE_CHECKING:
    from collections.abc import Callable

    from benchmarks.stream_cost.shared_cache.protocol import Cell, Family

pytestmark = pytest.mark.unit

_CONFIG = Path("reports/shared-worker-cache/v4/config.json")
_FROZEN_RATES = {"primary": 3000, "cold": 1000, "sensitivity": 500}
_FROZEN_WINDOWS = {"hot": 30, "active": 60, "sensitivity": 30}


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


def _record(
    cell: Cell,
    *,
    completed: int = 1_000,
    hits: int | None = None,
    misses: int = 0,
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
            "hits": completed if hits is None else hits,
            "misses": misses,
            "bypasses": 0,
        },
        "loop": loop,
        "lag": {"lag_windows": [[0.01, 0.02]]},
    }
    population = {
        "sample_count": sample_count,
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
    assert {cell.path for cell in cells} == set(PATHS)


def test_twelve_blocks_use_every_path_order_twice(frozen: Registration) -> None:
    orders = [path_order(block, PATHS) for block in range(12)]

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
    ("kind", "rate", "model", "expected"),
    [
        pytest.param("hot", 3000.0, "sync", 30, id="nominal-hot"),
        pytest.param("hot", 100.0, "sync", 102, id="sample-floor-extends-hot"),
        pytest.param("active", 300.0, "mixed", 68, id="mixed-needs-both-models"),
    ],
)
def test_window_preserves_the_percentile_sample_floor(
    registration: Registration, kind: str, rate: float, model: str, expected: float
) -> None:
    assert window_for(registration, kind, rate, model) == expected  # type: ignore[arg-type]


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
    registration: Registration, family: Family, ceiling: float | None, expected: int
) -> None:
    cell = probe_cells(registration)[0]
    probes = [_record(cell, completed=completed) for completed in (10_000, 20_000)]

    assert run.select_rate(registration, family, probes, ceiling) == expected


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        pytest.param({"completed_in_window": 900}, "registered fraction", id="late"),
        pytest.param({"loop": {"errors": 1}}, "overflow", id="errors"),
        pytest.param({"loop": {"overflow": 1}}, "overflow", id="overflow"),
        pytest.param({"loop": {"outstanding_at_end": 9}}, "backlog", id="backlog"),
        pytest.param({"sample_count": 9_999}, "sample floor", id="samples"),
    ],
)
def test_validation_rejects_overloaded_or_short_windows(
    registration: Registration, change: JsonDict, reason: str
) -> None:
    cell = validation_cells(
        registration, "primary", 100.0, {"hot": 30.0, "active": 60.0}
    )[0]
    record = _record(cell)
    workers = cast("list[JsonDict]", record["workers_measured"])
    if "loop" in change:
        cast("JsonDict", workers[0]["loop"]).update(cast("JsonDict", change["loop"]))
    elif "sample_count" in change:
        population = cast(
            "JsonDict", cast("JsonDict", record["populations"])["request"]
        )
        record["populations"] = {"request": {**population, "sample_count": 9_999}}
    else:
        record.update(change)

    failure = run.validation_failure(record, registration)

    assert failure is not None
    assert reason in failure


@pytest.mark.parametrize(
    ("completed", "expected"),
    [
        pytest.param(10_000, None, id="complete"),
        pytest.param(9_999, "identity", id="short"),
    ],
)
def test_cold_validation_requires_every_identity(
    registration: Registration, completed: int, expected: str | None
) -> None:
    cell = validation_cells(registration, "cold", 1000.0, {})[0]
    record = _record(cell)
    record["completed"] = completed

    failure = run.validation_failure(record, registration)

    assert (failure is None) if expected is None else (expected in str(failure))


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

    assert run.validation_failure(_record(cell), registration) is None


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
    family: Family,
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


def test_resume_rejects_another_revision(
    tmp_path: Path, registration: Registration
) -> None:
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "phase": "calibration",
                "environment": {
                    **run.environment(registration),
                    "revision": "0" * 40,
                },
                "cells": [],
            }
        )
    )

    with pytest.raises(BenchmarkSetupError, match="another phase, revision"):
        run.resumed_cells(report, "calibration", registration)


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


@pytest.mark.parametrize("model", ["sync", "async"])
def test_open_loop_records_errors_and_completions(model: str) -> None:
    assignment = Assignment(
        worker=0, workers=1, rate=200.0, requests=20, keys=tuple(range(20))
    )
    start = time.monotonic() + 0.01
    loop: LoopResult = (
        open_loop_sync(
            assignment,
            start,
            _reader({3}, 0.0),
            concurrency=2,
            outstanding_limit=8,
            drain_seconds=1.0,
            record=True,
        )
        if model == "sync"
        else asyncio.run(
            open_loop_async(
                assignment,
                start,
                _async_reader({3}, 0.0),  # type: ignore[arg-type]
                concurrency=2,
                outstanding_limit=8,
                drain_seconds=1.0,
                record=True,
            )
        )
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
    start = time.monotonic() + 0.01
    loop: LoopResult = (
        open_loop_sync(
            assignment,
            start,
            _reader(set(), 0.05),
            concurrency=1,
            outstanding_limit=2,
            drain_seconds=0.01,
            record=False,
        )
        if model == "sync"
        else asyncio.run(
            open_loop_async(
                assignment,
                start,
                _async_reader(set(), 0.05),  # type: ignore[arg-type]
                concurrency=1,
                outstanding_limit=2,
                drain_seconds=0.01,
                record=False,
            )
        )
    )

    assert loop.overflow > 0
    assert loop.outstanding_at_end > 0
    assert loop.latencies == []


@pytest.mark.parametrize("model", ["sync", "async"])
def test_closed_loop_stops_at_its_identity_quota(model: str) -> None:
    assignment = Assignment(
        worker=0, workers=2, rate=None, requests=10, keys=tuple(range(10))
    )
    start = time.monotonic()
    loop: LoopResult = (
        closed_loop_sync(assignment, start, 5.0, _reader({4}, 0.001), 2)
        if model == "sync"
        else asyncio.run(
            closed_loop_async(assignment, start, 5.0, _async_reader({4}, 0.001), 2)  # type: ignore[arg-type]
        )
    )

    assert (loop.offered, loop.completed, loop.errors) == (5, 4, 1)
    assert loop.elapsed < 5.0


@pytest.mark.parametrize(
    ("document", "error"),
    [
        pytest.param(None, LookupError, id="missing"),
        pytest.param({"payload": "abc", "revision": 2}, None, id="present"),
    ],
)
def test_checksum_requires_the_document(
    document: BsonDict | None, error: type[Exception] | None
) -> None:
    if error is None:
        assert checksum(document) == checksum({"payload": "abc", "revision": 2})
        return
    with pytest.raises(error):
        checksum(document)


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
) -> list[JsonDict]:
    cells = [
        cell
        for cell in comparison_cells(frozen, "confirmation")
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
    records = _comparison_records(frozen, shared_pss=50.0, blocks=2)
    records.append(_record(comparison_cells(frozen, "screening")[0], healthy=False))
    report.write_text(json.dumps({"cells": records}))

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


@pytest.mark.parametrize(
    "remove",
    [
        pytest.param("path", id="missing-path"),
        pytest.param("block", id="missing-block"),
        pytest.param("metric", id="missing-metric"),
    ],
)
def test_incomplete_pairs_are_missing(frozen: Registration, remove: str) -> None:
    records = _comparison_records(frozen, shared_pss=50.0, blocks=2)
    if remove == "path":
        records = [record for record in records if record["path"] != "shared"]
    elif remove == "block":
        records = [record for record in records if record["block"] == 0]
    else:
        shared = next(record for record in records if record["path"] == "shared")
        cast("list[JsonDict]", shared["workers_measured"])[0]["outcomes"] = {
            "hits": 0,
            "misses": 0,
            "bypasses": 0,
        }

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


def test_resume_accepts_the_same_revision(
    tmp_path: Path, registration: Registration
) -> None:
    report = tmp_path / "report.json"
    cells = [_record(smoke_cells(registration)[0])]
    report.write_text(
        json.dumps(
            {
                "phase": "smoke",
                "environment": run.environment(registration),
                "cells": cells,
            }
        )
    )

    assert run.resumed_cells(report, "smoke", registration) == cells


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
    start = time.monotonic()
    loop: LoopResult = (
        closed_loop_sync(assignment, start, 0.05, _reader(set(), 0.001), 2)
        if model == "sync"
        else asyncio.run(
            closed_loop_async(assignment, start, 0.05, _async_reader(set(), 0.001), 2)  # type: ignore[arg-type]
        )
    )

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
