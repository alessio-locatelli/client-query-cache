from __future__ import annotations

import asyncio
import time

import pytest

from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.shared_cache.fault_timeline import (
    _stream_openings,
    classify_requests,
    detect_recovery,
    merge_chunks,
    request_counts,
    stream_reopening_counts,
    timeline_generations,
    validate_request_counts,
)
from benchmarks.stream_cost.shared_cache.workload import (
    Assignment,
    LoopResult,
    open_loop_async,
    open_loop_sync,
)
from client_query_cache._types import JsonDict, NonNegativeInt

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("model", ["sync", "async"])
def test_open_loop_emits_request_offsets_only_when_timeline_is_enabled(
    model: str,
) -> None:
    assignment = Assignment(0, 1, 100.0, 1, (0,))
    start = time.monotonic() + 0.01
    events: list[JsonDict] = []
    loop_result: LoopResult

    if model == "sync":
        loop_result = open_loop_sync(
            assignment,
            start,
            lambda _key: None,
            concurrency=1,
            outstanding_limit=1,
            drain_seconds=0.1,
            record=True,
            timeline=events.append,
        )
    else:

        async def run() -> LoopResult:
            return await open_loop_async(
                assignment,
                start,
                _read,
                concurrency=1,
                outstanding_limit=1,
                drain_seconds=0.1,
                record=True,
                timeline=events.append,
            )

        async def _read(_key: NonNegativeInt) -> None:
            await asyncio.sleep(0)

        loop_result = asyncio.run(run())

    assert loop_result.completed == 1
    assert [event["state"] for event in events] == ["started", "completed"]
    assert events[0]["scheduled_offset"] == pytest.approx(0.0)
    completed_offset = events[1]["completed_offset"]
    issued_offset = events[1]["issued_offset"]
    assert isinstance(completed_offset, (int, float))
    assert isinstance(issued_offset, (int, float))
    assert completed_offset >= issued_offset
    assert "timeline" not in loop_result.summary()


def test_timeline_chunks_keep_delivered_events_and_classify_a_killed_share() -> None:
    chunks: list[JsonDict] = [
        {
            "events": [
                {
                    "state": "completed",
                    "ordinal": 0,
                    "scheduled_offset": 0.0,
                    "issued_offset": 0.01,
                    "completed_offset": 0.02,
                    "error": None,
                }
            ],
            "snapshot": {"offset": 0.25},
        },
        {
            "events": [
                {
                    "state": "started",
                    "ordinal": 1,
                    "scheduled_offset": 1.0,
                    "issued_offset": 1.02,
                }
            ],
            "snapshot": {"offset": 0.5},
        },
    ]

    events, snapshots = merge_chunks(chunks)
    requests = classify_requests((0, 1, 2), events, rate=1.0, killed_at=1.5)
    counts = validate_request_counts(requests, 3)

    offsets = [snapshot["offset"] for snapshot in snapshots]
    assert offsets == [0.25, 0.5]
    assert counts == {
        "completed": 1,
        "failed": 0,
        "interrupted": 1,
        "undelivered": 1,
    }


def test_request_classification_rejects_duplicate_terminal_outcomes() -> None:
    completed = {
        "ordinal": 0,
        "state": "completed",
        "scheduled_offset": 0.0,
        "issued_offset": 0.01,
        "completed_offset": 0.02,
    }

    with pytest.raises(BenchmarkSetupError, match="repeated terminal outcomes"):
        classify_requests((0,), (completed, completed), rate=1.0, killed_at=None)


def test_timeline_generations_default_missing_generation_and_sort_snapshots() -> None:
    snapshots: list[JsonDict] = [
        {"offset": 1.0},
        {"offset": 0.0, "generation": 0},
    ]

    assert timeline_generations(snapshots) == [[snapshots[1], snapshots[0]]]


@pytest.mark.parametrize("generation", [True, -1, "zero"])
def test_timeline_generations_reject_invalid_values(generation: object) -> None:
    with pytest.raises(BenchmarkSetupError, match="invalid generation"):
        timeline_generations([{"offset": 0.0, "generation": generation}])


def test_stream_reopening_counts_skip_generations_after_the_window() -> None:
    timelines: list[JsonDict] = [
        {"snapshots": [{"offset": 2.0, "generation": 0, "stream_openings": 1}]}
    ]

    assert stream_reopening_counts(timelines, injection_offset=0.0, window_end=1.0) == [
        0
    ]


def test_stream_reopening_counts_reject_a_counter_reset_within_a_generation() -> None:
    timeline: list[JsonDict] = [
        {
            "snapshots": [
                {"offset": 0.5, "generation": 0, "stream_openings": 2},
                {"offset": 1.0, "generation": 0, "stream_openings": 1},
            ]
        }
    ]

    with pytest.raises(BenchmarkSetupError, match="counter reset"):
        stream_reopening_counts(timeline, injection_offset=0.75, window_end=1.5)


@pytest.mark.parametrize(
    ("ordinals", "events", "message"),
    [
        pytest.param((0, 0), (), "repeats a request ordinal", id="duplicate-schedule"),
        pytest.param(
            (0,), ({"ordinal": 1, "state": "started"},), "unoffered", id="unoffered"
        ),
        pytest.param(
            (0,),
            ({"ordinal": 0, "state": "pending"},),
            "invalid request state",
            id="invalid-state",
        ),
        pytest.param(
            (0,),
            (
                {"ordinal": 0, "state": "started"},
                {"ordinal": 0, "state": "started"},
            ),
            "repeated request ordinal",
            id="duplicate-start",
        ),
    ],
)
def test_request_classification_rejects_invalid_schedule_and_events(
    ordinals: tuple[int, ...],
    events: tuple[JsonDict, ...],
    message: str,
) -> None:
    with pytest.raises(BenchmarkSetupError, match=message):
        classify_requests(ordinals, events, rate=1.0, killed_at=None)


@pytest.mark.parametrize(
    "snapshot",
    [{}, {"stream_openings": True}, {"stream_openings": -1}],
    ids=["missing", "boolean", "negative"],
)
def test_stream_openings_reject_invalid_snapshot_values(
    snapshot: JsonDict,
) -> None:
    with pytest.raises(BenchmarkSetupError, match="stream opening"):
        _stream_openings(snapshot)


def test_recovery_requires_before_interval_completions() -> None:
    with pytest.raises(BenchmarkSetupError, match="no before-interval completions"):
        detect_recovery(
            [],
            injection_offset=1.0,
            deadline=2.0,
            window_end=3.0,
            before_seconds=1.0,
        )


def test_request_counts_reject_unknown_states() -> None:
    with pytest.raises(BenchmarkSetupError, match="invalid state"):
        request_counts([{"state": "pending"}])


def test_fault_window_without_kill_classifies_only_completed_or_failed_requests() -> (
    None
):
    requests = classify_requests(
        (0, 1, 2),
        (
            {
                "ordinal": 0,
                "state": "completed",
                "issued_offset": 0.01,
                "completed_offset": 0.1,
            },
            {
                "ordinal": 1,
                "state": "failed",
                "issued_offset": 1.01,
                "completed_offset": 1.1,
            },
            {
                "ordinal": 2,
                "state": "completed",
                "issued_offset": 2.01,
                "completed_offset": 2.1,
            },
        ),
        rate=1.0,
        killed_at=None,
    )

    assert validate_request_counts(requests, 3) == {
        "completed": 2,
        "failed": 1,
        "interrupted": 0,
        "undelivered": 0,
    }


def test_incomplete_replacement_timeline_is_rejected() -> None:
    requests = classify_requests(
        (0, 1, 2),
        (
            {
                "ordinal": 0,
                "state": "completed",
                "issued_offset": 0.01,
                "completed_offset": 0.1,
            },
            {"ordinal": 1, "state": "started", "issued_offset": 1.1},
        ),
        rate=1.0,
        killed_at=None,
    )

    with pytest.raises(BenchmarkSetupError, match="expected offered schedule 3"):
        validate_request_counts(requests, 3)


def _completed_request(
    ordinal: NonNegativeInt,
    scheduled: float,
    latency: float,
) -> JsonDict:
    return {
        "ordinal": ordinal,
        "scheduled_offset": scheduled,
        "completed_offset": scheduled + latency,
        "resolved_offset": scheduled + latency,
        "state": "completed",
    }


def _baseline_requests(latency: float) -> list[JsonDict]:
    return [_completed_request(index, float(index), latency) for index in range(10)]


def _recovery(requests: list[JsonDict], *, deadline: float = 15.0) -> JsonDict:
    return detect_recovery(
        requests,
        injection_offset=10.0,
        deadline=deadline,
        window_end=15.0,
        before_seconds=10.0,
        backlog_grace_p99_multiple=2.0,
    )


def test_recovery_detector_accepts_fast_error_free_requests() -> None:
    requests = _baseline_requests(0.01) + [
        _completed_request(index, float(index), 0.01) for index in range(10, 15)
    ]

    recovery = _recovery(requests)

    assert recovery["recovered"] is True
    assert recovery["recovery_offset"] == 10


def test_later_latency_spike_does_not_revoke_recovery() -> None:
    requests = _baseline_requests(0.01)
    requests.extend(
        _completed_request(index, float(index), 0.1 if index == 14 else 0.01)
        for index in range(10, 15)
    )

    recovery = _recovery(requests)

    assert recovery["recovered"] is True
    assert recovery["recovery_offset"] == 10
    buckets = recovery["buckets"]
    assert isinstance(buckets, list)
    assert buckets[-1]["passed"] is False


@pytest.mark.parametrize(
    ("fault_state", "deadline", "expected_recovery"),
    [
        pytest.param("failed", 15.0, False, id="never-recovers"),
        pytest.param("late", 11.5, False, id="recovers-after-deadline"),
        pytest.param("slow", 15.0, False, id="error-free-but-slow"),
    ],
)
def test_recovery_detector_rejects_failure_slow_or_late_trials(
    fault_state: str,
    deadline: float,
    expected_recovery: bool,
) -> None:
    requests = _baseline_requests(0.01)
    for ordinal in range(10, 15):
        if fault_state == "failed" or (fault_state == "late" and ordinal < 12):
            requests.append(
                {
                    "ordinal": ordinal,
                    "scheduled_offset": float(ordinal),
                    "completed_offset": ordinal + 0.01,
                    "resolved_offset": ordinal + 0.01,
                    "state": "failed",
                }
            )
        else:
            latency = 0.1 if fault_state == "slow" else 0.01
            requests.append(_completed_request(ordinal, float(ordinal), latency))

    recovery = _recovery(requests, deadline=deadline)

    assert recovery["recovered"] is expected_recovery
    if fault_state == "late":
        assert recovery["after_interval_available"] is False


def test_surviving_workers_do_not_hide_a_missing_killed_worker() -> None:
    requests = _baseline_requests(0.01)
    for bucket in range(10, 15):
        for worker in range(4):
            ordinal = bucket * 4 + worker
            if worker == 0:
                requests.append(
                    {
                        "ordinal": ordinal,
                        "scheduled_offset": bucket + worker / 4,
                        "state": "undelivered",
                    }
                )
            else:
                requests.append(_completed_request(ordinal, bucket + worker / 4, 0.01))

    recovery = _recovery(requests)

    assert recovery["recovered"] is False
    buckets = recovery["buckets"]
    assert isinstance(buckets, list)
    assert all(
        bucket["completion_fraction"] == pytest.approx(0.75) for bucket in buckets
    )


def test_backlog_clear_waits_for_the_final_sub_one_percent_request() -> None:
    requests = _baseline_requests(0.3)
    requests.extend(
        _completed_request(index, 10 + index * 0.004, 0.01) for index in range(199)
    )
    requests.append(_completed_request(199, 10.99, 0.7))
    for bucket in range(11, 15):
        requests.extend(
            _completed_request(
                200 + bucket * 4 + worker,
                bucket + worker / 4,
                0.01,
            )
            for worker in range(4)
        )
    requests.extend(
        _completed_request(300 + index, 11 + index * 0.004, 0.01)
        for index in range(199)
    )

    recovery = _recovery(requests)

    buckets = recovery["buckets"]
    assert isinstance(buckets, list)
    first_bucket = buckets[0]
    assert first_bucket["completion_fraction"] == pytest.approx(0.995)
    assert first_bucket["request_p99_seconds"] == pytest.approx(0.01)
    assert first_bucket["backlog_clear"] is False
    assert recovery["recovered"] is True
    assert recovery["recovery_offset"] == 11


def test_recovery_allows_normal_requests_to_finish_across_bucket_boundary() -> None:
    requests = _baseline_requests(0.01)
    requests.extend(
        _completed_request(index, 10 + index * 0.004, 0.01) for index in range(199)
    )
    requests.append(_completed_request(199, 10.99, 0.02))
    for bucket in range(11, 15):
        requests.extend(
            _completed_request(
                200 + bucket * 4 + worker,
                bucket + worker / 4,
                0.01,
            )
            for worker in range(4)
        )

    recovery = _recovery(requests)

    buckets = recovery["buckets"]
    assert isinstance(buckets, list)
    assert buckets[0]["completion_fraction"] == pytest.approx(0.995)
    assert buckets[0]["request_p99_seconds"] == pytest.approx(0.01)
    assert buckets[0]["backlog_clear"] is True
    assert recovery["recovered"] is True
    assert recovery["recovery_offset"] == 10


def test_restart_counts_report_completed_failed_interrupted_and_undelivered() -> None:
    requests = classify_requests(
        (0, 1, 2, 3),
        (
            {
                "ordinal": 0,
                "state": "completed",
                "issued_offset": 0.01,
                "completed_offset": 0.02,
            },
            {
                "ordinal": 1,
                "state": "started",
                "issued_offset": 1.01,
            },
            {
                "ordinal": 2,
                "state": "failed",
                "issued_offset": 2.01,
                "completed_offset": 2.02,
                "error": "AutoReconnect",
            },
        ),
        rate=1.0,
        killed_at=1.5,
    )

    counts = validate_request_counts(requests, 4)

    assert counts == {
        "completed": 1,
        "failed": 1,
        "interrupted": 1,
        "undelivered": 1,
    }
