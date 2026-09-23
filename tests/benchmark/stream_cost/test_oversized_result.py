from __future__ import annotations

import pytest

from benchmarks.stream_cost.errors import BenchmarkConfigurationError
from benchmarks.stream_cost.oversized_result import (
    MINIMUM_ENCODER_REPETITIONS,
    OversizedResultSavingsMeasurement,
    OversizedResultWorkloadMeasurement,
    find_crossover_prefix_length,
    measure_oversized_result_savings,
    measure_oversized_result_workload,
    time_encoder_invocations,
)
from mongo_client_cache._core.codec import encode_value

pytestmark = pytest.mark.unit

_PADDING_BYTES = 200
_MAX_ENTRY_BYTES = 1_000


def _padded_documents(
    count: int, *, padding_bytes: int = _PADDING_BYTES
) -> list[dict[str, object]]:
    return [{"_id": index, "padding": "x" * padding_bytes} for index in range(count)]


def test_find_crossover_prefix_length_rejects_empty_documents() -> None:
    with pytest.raises(
        BenchmarkConfigurationError, match="documents must not be empty"
    ):
        find_crossover_prefix_length([], max_entry_bytes=_MAX_ENTRY_BYTES)


def test_find_crossover_prefix_length_rejects_non_positive_max_entry_bytes() -> None:
    with pytest.raises(BenchmarkConfigurationError, match="max_entry_bytes"):
        find_crossover_prefix_length(_padded_documents(5), max_entry_bytes=0)


def test_find_crossover_prefix_length_rejects_a_result_that_already_fits() -> None:
    documents = _padded_documents(2, padding_bytes=10)
    with pytest.raises(
        BenchmarkConfigurationError, match="must exceed max_entry_bytes"
    ):
        find_crossover_prefix_length(documents, max_entry_bytes=_MAX_ENTRY_BYTES)


def test_find_crossover_prefix_length_rejects_a_single_oversized_document() -> None:
    documents = _padded_documents(2, padding_bytes=_MAX_ENTRY_BYTES * 2)
    with pytest.raises(BenchmarkConfigurationError, match="individually exceed"):
        find_crossover_prefix_length(documents, max_entry_bytes=_MAX_ENTRY_BYTES)


def test_find_crossover_prefix_length_rejects_a_later_oversized_document() -> None:
    documents = _padded_documents(5) + _padded_documents(
        1, padding_bytes=_MAX_ENTRY_BYTES * 2
    )
    with pytest.raises(BenchmarkConfigurationError, match="individually exceed"):
        find_crossover_prefix_length(documents, max_entry_bytes=_MAX_ENTRY_BYTES)


def test_find_crossover_prefix_length_finds_the_exact_crossover() -> None:
    documents = _padded_documents(20)
    prefix_length = find_crossover_prefix_length(
        documents, max_entry_bytes=_MAX_ENTRY_BYTES
    )
    below = encode_value(documents[: prefix_length - 1])
    at_or_above = encode_value(documents[:prefix_length])
    assert len(below) <= _MAX_ENTRY_BYTES
    assert len(at_or_above) > _MAX_ENTRY_BYTES


def test_time_encoder_invocations_rejects_too_few_repetitions() -> None:
    with pytest.raises(BenchmarkConfigurationError, match="repetitions"):
        time_encoder_invocations({"a": 1}, repetitions=MINIMUM_ENCODER_REPETITIONS - 1)


def test_time_encoder_invocations_returns_one_cost_per_repetition() -> None:
    costs = time_encoder_invocations({"a": 1}, repetitions=MINIMUM_ENCODER_REPETITIONS)
    assert len(costs) == MINIMUM_ENCODER_REPETITIONS
    assert all(cost >= 0 for cost in costs)


def test_measure_oversized_result_savings_computes_medians_and_threshold() -> None:
    documents = _padded_documents(20)
    measurement = measure_oversized_result_savings(
        documents,
        max_entry_bytes=_MAX_ENTRY_BYTES,
        repetitions=MINIMUM_ENCODER_REPETITIONS,
        acceptable_savings_threshold_seconds=0.0,
    )
    assert isinstance(measurement, OversizedResultSavingsMeasurement)
    assert measurement.prefix_length < len(documents)
    assert measurement.prefix_cost_seconds >= 0
    assert measurement.full_cost_seconds >= 0
    assert measurement.meets_acceptable_savings_threshold is (
        measurement.savings_seconds >= 0.0
    )


def test_oversized_result_savings_measurement_rejects_a_negative_threshold() -> None:
    with pytest.raises(
        BenchmarkConfigurationError, match="acceptable_savings_threshold_seconds"
    ):
        OversizedResultSavingsMeasurement(
            prefix_length=1,
            prefix_costs_seconds=(0.1,),
            full_costs_seconds=(0.2,),
            acceptable_savings_threshold_seconds=-1.0,
        )


def test_oversized_result_workload_measurement_rejects_a_negative_cost() -> None:
    savings = OversizedResultSavingsMeasurement(
        prefix_length=1,
        prefix_costs_seconds=(0.1,),
        full_costs_seconds=(0.2,),
        acceptable_savings_threshold_seconds=0.0,
    )
    with pytest.raises(BenchmarkConfigurationError, match="end_to_end_cost_seconds"):
        OversizedResultWorkloadMeasurement(
            end_to_end_cost_seconds=-1.0, savings=savings
        )


def test_measure_oversized_result_workload_keeps_costs_separate() -> None:
    documents = _padded_documents(20)
    measurement = measure_oversized_result_workload(
        lambda: documents,
        max_entry_bytes=_MAX_ENTRY_BYTES,
        repetitions=MINIMUM_ENCODER_REPETITIONS,
        acceptable_savings_threshold_seconds=0.0,
    )
    assert measurement.end_to_end_cost_seconds >= 0
    assert isinstance(measurement.savings, OversizedResultSavingsMeasurement)
    assert measurement.savings.prefix_length < len(documents)
