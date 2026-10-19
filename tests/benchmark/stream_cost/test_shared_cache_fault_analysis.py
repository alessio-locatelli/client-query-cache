from __future__ import annotations

import copy
import json
from dataclasses import asdict
from pathlib import Path
from typing import Literal, cast

import pytest

from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.shared_cache.analysis import (
    _fault_range,
    _fault_repetition_passed,
    analyze_worker_faults,
)
from benchmarks.stream_cost.shared_cache.fault_timeline import (
    classify_requests,
    detect_recovery,
    stream_reopening_counts,
    validate_request_counts,
)
from benchmarks.stream_cost.shared_cache.protocol import (
    RecoveryFaultCell,
    Registration,
    fault_recovery_cells,
)
from client_query_cache._types import JsonDict

pytestmark = pytest.mark.unit

_CONFIG = Path("reports/concurrent-worker-workload/v1/config.json")


def _registration() -> Registration:
    raw = copy.deepcopy(json.loads(_CONFIG.read_text(encoding="utf-8")))
    raw["status"] = "frozen"
    raw["frozen"]["rates"] = {"steady": 2, "stepdown": 2}
    raw["frozen"]["window_seconds"] = {"active": 6}
    raw["calibration"]["caps"]["stepdown"] = 10
    raw["calibration"]["families"]["stepdown"] = {
        "probe_workload": "hot",
        "topology": "three-member",
        "cells": [["active", "async", 4]],
    }
    raw["fault_recovery"] = {
        "cases": [
            "connection-loss",
            "stepdown",
            "history-loss",
            "worker-restart",
        ],
        "rate_families": {
            "single-member": "steady",
            "three-member": "stepdown",
        },
        "repetitions": 1,
        "before_seconds": 2,
        "after_seconds": 4,
        "recovery_deadline_seconds": 3,
        "before_interval_seconds": 2,
        "timeline_cadence_seconds": 0.25,
        "error_classes": {
            "connection-loss": ["AutoReconnect"],
            "stepdown": ["AutoReconnect"],
            "history-loss": ["ChangeStreamHistoryLost"],
            "worker-restart": ["AutoReconnect"],
        },
        "smoke": {
            "rate": 2,
            "before_seconds": 2,
            "after_seconds": 4,
            "recovery_deadline_seconds": 3,
        },
    }
    return Registration(raw, "worker-fault-analysis-test")


def _completed(ordinal: int, scheduled: float) -> JsonDict:
    return {
        "ordinal": ordinal,
        "state": "completed",
        "scheduled_offset": scheduled,
        "issued_offset": scheduled + 0.001,
        "completed_offset": scheduled + 0.01,
        "error": None,
    }


def _restart_record(
    registration: Registration,
    path: Literal["direct", "independent"] = "direct",
) -> JsonDict:
    cell = next(
        cell
        for cell in fault_recovery_cells(registration, (path,))
        if isinstance(cell, RecoveryFaultCell) and cell.fault_case == "worker-restart"
    )
    assert isinstance(cell, RecoveryFaultCell)
    assert cell.rate is not None
    assert cell.window_seconds is not None
    timelines: list[JsonDict] = []
    requests: list[JsonDict] = []
    for index in range(cell.workers):
        ordinals = tuple(
            range(index, round(cell.rate * cell.window_seconds), cell.workers)
        )
        events: list[JsonDict] = []
        for ordinal in ordinals:
            scheduled = ordinal / cell.rate
            if index == 0 and ordinal == 4:
                events.append(
                    {
                        "ordinal": ordinal,
                        "state": "started",
                        "scheduled_offset": scheduled,
                        "issued_offset": scheduled + 0.01,
                    }
                )
            else:
                events.append(_completed(ordinal, scheduled))
        killed_at = 2.5 if index == 0 else None
        worker_requests = classify_requests(
            ordinals,
            events,
            rate=cell.rate,
            killed_at=killed_at,
        )
        requests.extend(worker_requests)
        timelines.append(
            {
                "index": index,
                "events": events,
                "snapshots": [
                    {
                        "offset": offset,
                        "generation": (1 if index == 0 and offset >= 2.75 else 0),
                        "hits": (
                            100
                            if index == 0 and path == "independent" and offset <= 2.25
                            else 1
                            if index == 0 and path == "independent" and offset >= 4.5
                            else 0
                        ),
                        "misses": (
                            3
                            if index == 0 and path == "independent" and offset >= 2.75
                            else 0
                        ),
                        "bypasses": 0,
                        "bypass_reasons": (
                            {"network": 8}
                            if index == 0 and path == "independent" and offset >= 5.5
                            else {"network": 3}
                            if index == 0
                            and path == "independent"
                            and offset > 2.75
                            and offset < 5.5
                            else {"network": 2}
                            if index == 0
                            and path == "independent"
                            and 2.5 < offset < 3.0
                            else {"network": 6}
                            if index == 0 and path == "independent" and offset >= 2.25
                            else {"network": 5}
                            if index == 0 and path == "independent"
                            else {}
                        ),
                        "health": (
                            "unhealthy"
                            if path == "independent" and 2.0 < offset < 2.5
                            else "healthy"
                            if path == "independent" and offset >= 2.75
                            else "healthy"
                            if path == "independent" and offset >= 0.25
                            else None
                        ),
                        "streams": 1 if path == "independent" else 0,
                        "stream_openings": 1 if path == "independent" else 0,
                        "stream_operation_times": (
                            [(200, 1)]
                            if path == "independent" and index == 0 and offset >= 2.75
                            else [(100 + index, 1)]
                            if path == "independent"
                            else []
                        ),
                    }
                    for offset in (0.25, 1.5, 2.25, 2.75, 3.5, 4.5, 5.5)
                ],
                "scheduled_ordinals": ordinals,
                "killed_at": killed_at,
                "replacement_ready_offset": 2.5 if index == 0 else None,
            }
        )
    counts = validate_request_counts(requests, round(cell.rate * cell.window_seconds))
    recovery = detect_recovery(
        requests,
        injection_offset=cell.injection_offset_seconds,
        deadline=cell.injection_offset_seconds + cell.recovery_deadline_seconds,
        window_end=cell.window_seconds,
        before_seconds=2.0,
        replacement_ready_offset=2.5,
    )
    return {
        **asdict(cell),
        "healthy": True,
        "outcome": "recovered" if recovery["recovered"] else "not-recovered",
        "injection": {
            "actual_offset_seconds": cell.injection_offset_seconds,
            "registered_offset_seconds": cell.injection_offset_seconds,
        },
        "recovery": recovery,
        "requests": {
            "offered": round(cell.rate * cell.window_seconds),
            "counts": counts,
            "timeline": timelines,
            "latencies": {
                "before": {
                    "p50_seconds": 0.01,
                    "p95_seconds": 0.01,
                    "p99_seconds": 0.01,
                },
                "during": {
                    "p50_seconds": 0.01,
                    "p95_seconds": 0.01,
                    "p99_seconds": 0.01,
                },
                "after": {
                    "p50_seconds": 0.01,
                    "p95_seconds": 0.01,
                    "p99_seconds": 0.01,
                },
            },
        },
        "worker_details": {
            "replacement_ready_offset": 2.5,
            "replacement_ready": {"priming_misses": 3 if path == "independent" else 0},
        },
        "correctness": {"available": True, "passed": True},
        "writes": {"failed": 0, "unknown": 0},
        "command_failures": {},
        "worker_cpu_seconds": 1.0,
        "server_cpu_seconds": 2.0,
    }


def test_analysis_reports_recovery_and_all_restart_request_outcomes() -> None:
    registration = _registration()
    record = _restart_record(registration)

    report = analyze_worker_faults([record], registration)

    report_cases = report["cases"]
    assert isinstance(report_cases, list)
    restart = next(
        case
        for case in report_cases
        if case["case"] == "worker-restart" and case["path"] == "direct"
    )
    repetition = restart["repetitions"][0]
    assert repetition["replacement_ready_seconds"] == pytest.approx(0.5)
    restart_summary = cast("JsonDict", restart["median_and_range"])
    assert restart_summary["replacement_ready_seconds"] == {
        "median": 0.5,
        "min": 0.5,
        "max": 0.5,
    }
    assert repetition["request_counts"] == {
        "completed": 11,
        "failed": 0,
        "interrupted": 1,
        "undelivered": 0,
    }
    assert repetition["recovery"]["recovery_offset"] == 3
    assert repetition["replacement_repriming_misses"] == 0
    assert repetition["stream_reopenings"] == 0
    assert repetition["stream_reopenings_by_worker"] == [0, 0, 0, 0]
    assert report["complete"] is False

    cached_record = _restart_record(registration, "independent")
    cached_report = analyze_worker_faults([cached_record], registration)
    cached_cases = cached_report["cases"]
    assert isinstance(cached_cases, list)
    cached_restart = next(
        case
        for case in cached_cases
        if case["case"] == "worker-restart" and case["path"] == "independent"
    )
    cached_repetition = cached_restart["repetitions"][0]
    assert cached_repetition["replacement_ready_seconds"] == pytest.approx(0.5)
    assert cached_repetition["replacement_repriming_misses"] == 3
    assert cached_repetition["bypasses_by_reason"] == {"network": 3}
    assert cached_repetition["time_to_stream_health_seconds"] == pytest.approx(0.75)
    assert cached_repetition["time_to_cache_hit_seconds"] == pytest.approx(2.5)
    cached_summary = cast("JsonDict", cached_restart["median_and_range"])
    assert cached_summary["time_to_stream_health_seconds"] == {
        "median": 0.75,
        "min": 0.75,
        "max": 0.75,
    }
    assert cached_summary["time_to_cache_hit_seconds"] == {
        "median": 2.5,
        "min": 2.5,
        "max": 2.5,
    }
    assert cached_repetition["stream_reopenings"] == 1
    assert cached_repetition["stream_reopenings_by_worker"] == [1, 0, 0, 0]


def test_fault_bypass_summary_ignores_non_increasing_counters() -> None:
    registration = _registration()
    record = _restart_record(registration, "independent")
    timelines = cast("list[JsonDict]", cast("JsonDict", record["requests"])["timeline"])
    worker_snapshots = cast("list[JsonDict]", timelines[0]["snapshots"])
    for snapshot in worker_snapshots:
        snapshot["bypass_reasons"] = {"network": 0}

    report = analyze_worker_faults([record], registration)

    cases = cast("list[JsonDict]", report["cases"])
    restart = next(
        case
        for case in cases
        if case["case"] == "worker-restart" and case["path"] == "independent"
    )
    assert cast("list[JsonDict]", restart["repetitions"])[0]["bypasses_by_reason"] == {}


def test_fault_summary_keeps_unavailable_recovery_measures_explicit() -> None:
    registration = _registration()
    record = _restart_record(registration, "independent")
    timelines = cast("list[JsonDict]", cast("JsonDict", record["requests"])["timeline"])
    for timeline in timelines:
        snapshots = cast("list[JsonDict]", timeline["snapshots"])
        for snapshot in snapshots:
            snapshot["hits"] = 0

    report = analyze_worker_faults([record], registration)

    cases = cast("list[JsonDict]", report["cases"])
    restart = next(
        case
        for case in cases
        if case["case"] == "worker-restart" and case["path"] == "independent"
    )
    summary = cast("JsonDict", restart["median_and_range"])
    assert summary["time_to_cache_hit_seconds"] is None


def test_analysis_keeps_unrecovered_trials_and_empty_snapshot_intervals() -> None:
    registration = _registration()
    record = _restart_record(registration)
    cell = next(
        cell
        for cell in fault_recovery_cells(registration)
        if cell.fault_case == record["fault_case"] and cell.path == record["path"]
    )
    assert cell.rate is not None
    assert cell.window_seconds is not None
    request_data = record["requests"]
    assert isinstance(request_data, dict)
    timelines = request_data["timeline"]
    assert isinstance(timelines, list)
    requests: list[JsonDict] = []
    for timeline in timelines:
        assert isinstance(timeline, dict)
        events = cast("list[JsonDict]", timeline["events"])
        timeline["events"] = [
            event
            for event in events
            if cast("float", event["scheduled_offset"]) < cell.injection_offset_seconds
        ]
        timeline["snapshots"] = [
            {**snapshot, "offset": cell.window_seconds + 1.0}
            for snapshot in timeline["snapshots"]
        ]
        requests.extend(
            classify_requests(
                cast("list[int]", timeline["scheduled_ordinals"]),
                cast("list[JsonDict]", timeline["events"]),
                rate=cell.rate,
                killed_at=timeline["killed_at"],
            )
        )
    request_data["counts"] = validate_request_counts(
        requests, round(cell.rate * cell.window_seconds)
    )
    recovery = detect_recovery(
        requests,
        injection_offset=cell.injection_offset_seconds,
        deadline=cell.injection_offset_seconds + cell.recovery_deadline_seconds,
        window_end=cell.window_seconds,
        before_seconds=2.0,
        replacement_ready_offset=2.5,
    )
    record["recovery"] = recovery
    record["outcome"] = "not-recovered"

    report = analyze_worker_faults([record], registration)
    cases = cast("list[JsonDict]", report["cases"])
    repetition = next(
        repetition
        for case in cases
        if case["case"] == record["fault_case"] and case["path"] == record["path"]
        for repetition in cast("list[JsonDict]", case["repetitions"])
        if repetition["healthy"]
    )

    recovery = cast("JsonDict", repetition["recovery"])
    assert recovery["recovered"] is False
    assert repetition["time_to_cache_hit_seconds"] is None
    assert repetition["replacement_repriming_misses"] == 0


def test_analysis_rejects_duplicate_unregistered_and_mismatched_trials() -> None:
    registration = _registration()
    record = _restart_record(registration)
    with pytest.raises(BenchmarkSetupError, match="duplicate or unregistered"):
        analyze_worker_faults([record, record], registration)

    unregistered = _restart_record(registration)
    unregistered["fault_case"] = "unregistered"
    with pytest.raises(BenchmarkSetupError, match="duplicate or unregistered"):
        analyze_worker_faults([unregistered], registration)

    mismatch = _restart_record(registration)
    mismatch["workers"] = 3
    with pytest.raises(BenchmarkSetupError, match="differs from registration"):
        analyze_worker_faults([mismatch], registration)


def test_analysis_skips_missing_latency_distributions_and_empty_ranges() -> None:
    registration = _registration()
    record = _restart_record(registration)
    request_data = record["requests"]
    assert isinstance(request_data, dict)
    latencies = request_data["latencies"]
    assert isinstance(latencies, dict)
    latencies["during"] = None

    report = analyze_worker_faults([record], registration)

    assert report["complete"] is False
    assert _fault_range([]) is None


def test_resumed_stream_aggregate_counts_as_reopening_without_new_operation_time() -> (
    None
):
    timeline: JsonDict = {
        "snapshots": [
            {
                "offset": 1.0,
                "generation": 0,
                "stream_openings": 1,
                "stream_operation_times": [(100, 1)],
            },
            {
                "offset": 2.0,
                "generation": 0,
                "stream_openings": 2,
                "stream_operation_times": [(100, 1)],
            },
        ]
    }

    assert stream_reopening_counts(
        [timeline], injection_offset=1.5, window_end=3.0
    ) == [1]


def test_analysis_rejects_reported_request_count_mismatch() -> None:
    registration = _registration()
    record = _restart_record(registration)
    requests = record["requests"]
    assert isinstance(requests, dict)
    counts = requests["counts"]
    assert isinstance(counts, dict)
    completed = counts["completed"]
    assert isinstance(completed, int)
    counts["completed"] = completed + 1

    with pytest.raises(BenchmarkSetupError, match="counts differ from timeline"):
        analyze_worker_faults([record], registration)


def test_analysis_rejects_recovery_that_differs_from_the_request_timeline() -> None:
    registration = _registration()
    record = _restart_record(registration)
    recovery = record["recovery"]
    assert isinstance(recovery, dict)
    recovery["recovered"] = not recovery["recovered"]

    with pytest.raises(BenchmarkSetupError, match="differs from its timeline"):
        analyze_worker_faults([record], registration)


def test_analysis_rejects_a_worker_timeline_without_snapshots() -> None:
    registration = _registration()
    record = _restart_record(registration)
    requests = record["requests"]
    assert isinstance(requests, dict)
    timelines = requests["timeline"]
    assert isinstance(timelines, list)
    snapshots = timelines[0]["snapshots"]
    assert isinstance(snapshots, list)
    snapshots.clear()

    with pytest.raises(BenchmarkSetupError, match="has no snapshots"):
        analyze_worker_faults([record], registration)


def test_analysis_retains_missing_and_unhealthy_repetitions() -> None:
    registration = _registration()
    incomplete = analyze_worker_faults([], registration)
    assert incomplete["complete"] is False
    assert incomplete["pass"] is False
    incomplete_cases = cast("list[JsonDict]", incomplete["cases"])
    assert all(
        repetition["failure"] == "missing trial"
        for case in incomplete_cases
        for repetition in cast("list[JsonDict]", case["repetitions"])
    )

    record = _restart_record(registration)
    record["healthy"] = False
    record["failure"] = "replica set setup failed"
    failed = analyze_worker_faults([record], registration)
    failed_cases = cast("list[JsonDict]", failed["cases"])
    restart = next(
        case
        for case in failed_cases
        if case["case"] == "worker-restart" and case["path"] == "direct"
    )
    repetitions = cast("list[JsonDict]", restart["repetitions"])
    assert repetitions[0]["failure"] == "replica set setup failed"


def test_fault_repetition_requires_recovery_and_correctness_fields() -> None:
    assert _fault_repetition_passed({"healthy": False}) is False
    assert _fault_repetition_passed({"healthy": True}) is False
