from __future__ import annotations

import math
from typing import TYPE_CHECKING, cast

from benchmarks.stream_cost.errors import BenchmarkSetupError
from client_query_cache._types import (
    NonNegativeFloat,
    NonNegativeInt,
    PositiveFloat,
    Probability,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from benchmarks.stream_cost.shared_cache.worker import Payload


def merge_chunks(chunks: Iterable[Payload]) -> tuple[list[Payload], list[Payload]]:
    events: list[Payload] = []
    snapshots: list[Payload] = []
    for chunk in chunks:
        events.extend(cast("list[Payload]", chunk["events"]))
        snapshots.append(cast("Payload", chunk["snapshot"]))
    return events, snapshots


def timeline_generations(snapshots: Iterable[Payload]) -> list[list[Payload]]:
    ordered = sorted(snapshots, key=lambda snapshot: cast("float", snapshot["offset"]))
    generations: list[list[Payload]] = []
    generation_numbers: list[NonNegativeInt] = []
    for snapshot in ordered:
        try:
            raw_generation = snapshot["generation"]
        except KeyError:
            raw_generation = 0
        if (
            not isinstance(raw_generation, int)
            or isinstance(raw_generation, bool)
            or raw_generation < 0
        ):
            raise BenchmarkSetupError("fault snapshot has an invalid generation")
        generation = raw_generation
        if generation_numbers and generation_numbers[-1] == generation:
            generations[-1].append(snapshot)
        else:
            generation_numbers.append(generation)
            generations.append([snapshot])
    return generations


def stream_reopening_counts(
    timelines: Iterable[Payload],
    *,
    injection_offset: NonNegativeFloat,
    window_end: NonNegativeFloat,
) -> list[NonNegativeInt]:
    counts: list[NonNegativeInt] = []
    for timeline in timelines:
        snapshots = cast("list[Payload]", timeline["snapshots"])
        total = 0
        for generation in timeline_generations(snapshots):
            observed = [
                snapshot
                for snapshot in generation
                if cast("float", snapshot["offset"]) <= window_end
            ]
            if not observed:
                continue
            before_fault = [
                snapshot
                for snapshot in observed
                if cast("float", snapshot["offset"]) <= injection_offset
            ]
            previous_count = _stream_openings(before_fault[-1]) if before_fault else 0
            current_count = _stream_openings(observed[-1])
            if current_count < previous_count:
                raise BenchmarkSetupError(
                    "stream opening counter reset within a worker generation"
                )
            total += current_count - previous_count
        counts.append(total)
    return counts


def _stream_openings(snapshot: Payload) -> NonNegativeInt:
    try:
        value = snapshot["stream_openings"]
    except KeyError:
        raise BenchmarkSetupError("fault snapshot lacks stream opening count") from None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise BenchmarkSetupError("fault snapshot has invalid stream opening count")
    return value


def classify_requests(
    ordinals: Iterable[NonNegativeInt],
    events: Iterable[Payload],
    *,
    rate: PositiveFloat,
    killed_at: NonNegativeFloat | None,
) -> list[Payload]:
    scheduled_ordinals = tuple(ordinals)
    expected = frozenset(scheduled_ordinals)
    if len(expected) != len(scheduled_ordinals):
        raise BenchmarkSetupError("fault schedule repeats a request ordinal")
    latest: dict[NonNegativeInt, Payload] = {}
    started: set[NonNegativeInt] = set()
    terminal: set[NonNegativeInt] = set()
    for event in events:
        ordinal = cast("NonNegativeInt", event["ordinal"])
        if ordinal not in expected:
            raise BenchmarkSetupError("worker timeline contains an unoffered ordinal")
        state = event["state"]
        if state not in {"started", "completed", "failed"}:
            raise BenchmarkSetupError(
                "worker timeline contains an invalid request state"
            )
        if state == "started":
            if ordinal in started or ordinal in terminal:
                raise BenchmarkSetupError(
                    "worker timeline contains a repeated request ordinal"
                )
            started.add(ordinal)
        else:
            if ordinal in terminal:
                raise BenchmarkSetupError(
                    "worker timeline contains repeated terminal outcomes"
                )
            terminal.add(ordinal)
        latest[ordinal] = event

    requests: list[Payload] = []
    for ordinal in scheduled_ordinals:
        scheduled = ordinal / rate
        try:
            event = latest[ordinal]
        except KeyError:
            event = {}
        try:
            event_state = cast("str", event["state"])
        except KeyError:
            event_state = ""
        if event_state in {"completed", "failed"}:
            request: Payload = {
                "ordinal": ordinal,
                "scheduled_offset": scheduled,
                "issued_offset": event["issued_offset"],
                "completed_offset": event["completed_offset"],
                "resolved_offset": event["completed_offset"],
                "state": event_state,
            }
            try:
                request["error"] = event["error"]
            except KeyError:
                pass
        elif killed_at is not None and scheduled < killed_at:
            request = {
                "ordinal": ordinal,
                "scheduled_offset": scheduled,
                "state": "interrupted",
                "resolved_offset": killed_at,
            }
        elif event_state == "started":
            # An issued request with no terminal outcome is outside the four
            # registered classes. Leave it unclassified so count validation
            # rejects the trial instead of hiding an incomplete replacement.
            continue
        else:
            request = {
                "ordinal": ordinal,
                "scheduled_offset": scheduled,
                "state": "undelivered",
            }
        requests.append(request)
    return requests


def detect_recovery(
    requests: Iterable[Payload],
    *,
    injection_offset: NonNegativeFloat,
    deadline: NonNegativeFloat,
    window_end: NonNegativeFloat,
    before_seconds: PositiveFloat,
    replacement_ready_offset: NonNegativeFloat | None = None,
    bucket_seconds: PositiveFloat = 1.0,
    minimum_completion_fraction: Probability = 0.99,
    request_p99_multiple: PositiveFloat = 2.0,
    backlog_grace_p99_multiple: NonNegativeFloat = 0.0,
) -> Payload:
    materialized = list(requests)
    before = [
        cast("float", request["completed_offset"])
        - cast("float", request["scheduled_offset"])
        for request in materialized
        if request["state"] == "completed"
        and injection_offset - before_seconds
        <= cast("float", request["completed_offset"])
        < injection_offset
    ]
    if not before:
        raise BenchmarkSetupError("fault timeline has no before-interval completions")
    before_p99 = sorted(before)[min(len(before) - 1, math.ceil(0.99 * len(before)) - 1)]
    backlog_grace_seconds = backlog_grace_p99_multiple * before_p99
    buckets: list[Payload] = []
    first_bucket = math.ceil(injection_offset / bucket_seconds)
    last_bucket = math.ceil(window_end / bucket_seconds)
    for bucket_index in range(first_bucket, last_bucket):
        bucket = bucket_index * bucket_seconds
        end = bucket + bucket_seconds
        scheduled = [
            request
            for request in materialized
            if bucket <= cast("float", request["scheduled_offset"]) < end
        ]
        completed = [
            request
            for request in materialized
            if request["state"] == "completed"
            and bucket <= cast("float", request["completed_offset"]) < end
        ]
        failed = [
            request
            for request in materialized
            if request["state"] == "failed"
            and bucket <= cast("float", request["completed_offset"]) < end
        ]
        latencies = [
            cast("float", request["completed_offset"])
            - cast("float", request["scheduled_offset"])
            for request in completed
        ]
        earlier = [
            request
            for request in materialized
            if cast("float", request["scheduled_offset"]) < end
        ]
        backlog_clear = all(
            request["state"] in {"completed", "failed", "interrupted"}
            and cast("float", request["resolved_offset"]) <= end + backlog_grace_seconds
            for request in earlier
        )
        completion_fraction = len(completed) / len(scheduled) if scheduled else 1.0
        p99 = (
            sorted(latencies)[
                min(len(latencies) - 1, math.ceil(0.99 * len(latencies)) - 1)
            ]
            if latencies
            else None
        )
        ready = replacement_ready_offset is None or bucket >= replacement_ready_offset
        passed = (
            ready
            and not failed
            and completion_fraction >= minimum_completion_fraction
            and p99 is not None
            and p99 <= request_p99_multiple * before_p99
            and backlog_clear
        )
        buckets.append(
            {
                "start_offset": bucket,
                "scheduled": len(scheduled),
                "completed": len(completed),
                "failed": len(failed),
                "completion_fraction": completion_fraction,
                "request_p99_seconds": p99,
                "backlog_clear": backlog_clear,
                "replacement_ready": ready,
                "passed": passed,
            }
        )

    recovery_offset = None
    for bucket_record in buckets:
        if cast("bool", bucket_record["passed"]):
            recovery_offset = bucket_record["start_offset"]
            break
    recovered = (
        recovery_offset is not None and cast("float", recovery_offset) <= deadline
    )
    return {
        "recovered": recovered,
        "recovery_offset": recovery_offset if recovered else None,
        "time_to_recovery_seconds": (
            cast("float", recovery_offset) - injection_offset if recovered else None
        ),
        "before_request_p99_seconds": before_p99,
        "backlog_grace_seconds": backlog_grace_seconds,
        "after_interval_available": recovered,
        "buckets": buckets,
    }


def request_counts(requests: Iterable[Payload]) -> Payload:
    counts: Payload = {
        "completed": 0,
        "failed": 0,
        "interrupted": 0,
        "undelivered": 0,
    }
    for request in requests:
        state = cast("str", request["state"])
        if state not in counts:
            raise BenchmarkSetupError("request timeline has an invalid state")
        counts[state] = cast("int", counts[state]) + 1
    return counts


def validate_request_counts(
    requests: Iterable[Payload], offered: NonNegativeInt
) -> Payload:
    counts = request_counts(list(requests))
    total = sum(cast("int", counts[state]) for state in counts)
    if total != offered:
        message = (
            f"fault request counts total {total}, expected offered schedule {offered}"
        )
        raise BenchmarkSetupError(message)
    return counts
