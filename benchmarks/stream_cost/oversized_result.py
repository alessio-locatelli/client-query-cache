from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from benchmarks.stream_cost.errors import BenchmarkConfigurationError
from client_query_cache._core.codec import encode_value
from client_query_cache._types import NonNegativeInt, PositiveInt

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from bson.codec_options import CodecOptions

MINIMUM_ENCODER_REPETITIONS = 5


def _encoded_prefix_size(
    documents: Sequence[Mapping[str, object]],
    prefix_length: NonNegativeInt,
    codec_options: CodecOptions[Any] | None,
) -> NonNegativeInt:
    return len(encode_value(list(documents[:prefix_length]), codec_options))


def _encoded_single_document_size(
    document: Mapping[str, object], codec_options: CodecOptions[Any] | None
) -> NonNegativeInt:
    return len(encode_value([document], codec_options))


def find_crossover_prefix_length(
    documents: Sequence[Mapping[str, object]],
    *,
    max_entry_bytes: PositiveInt,
    codec_options: CodecOptions[Any] | None = None,
) -> NonNegativeInt:
    if max_entry_bytes <= 0:
        message = "max_entry_bytes must be positive"
        raise BenchmarkConfigurationError(message)
    if not documents:
        message = "documents must not be empty"
        raise BenchmarkConfigurationError(message)
    full_size = _encoded_prefix_size(documents, len(documents), codec_options)
    if full_size <= max_entry_bytes:
        message = (
            "the full result must exceed max_entry_bytes once enveloped and "
            "encoded to be a valid oversized-result workload"
        )
        raise BenchmarkConfigurationError(message)
    oversized_indices = [
        index
        for index, document in enumerate(documents)
        if _encoded_single_document_size(document, codec_options) > max_entry_bytes
    ]
    if oversized_indices:
        message = (
            f"document(s) at index {oversized_indices} individually exceed "
            "max_entry_bytes; the oversized-result workload requires "
            "individually-fitting documents whose aggregate encoded size "
            "exceeds the limit"
        )
        raise BenchmarkConfigurationError(message)
    low, high = 1, len(documents)
    while high - low > 1:
        mid = (low + high) // 2
        if _encoded_prefix_size(documents, mid, codec_options) > max_entry_bytes:
            high = mid
        else:
            low = mid
    return high


def time_encoder_invocations(
    value: object,
    *,
    codec_options: CodecOptions[Any] | None = None,
    repetitions: PositiveInt,
) -> tuple[float, ...]:
    if repetitions < MINIMUM_ENCODER_REPETITIONS:
        message = (
            f"repetitions ({repetitions}) is below the pre-registered minimum of "
            f"{MINIMUM_ENCODER_REPETITIONS}"
        )
        raise BenchmarkConfigurationError(message)
    costs: list[float] = []
    for _ in range(repetitions):
        start = time.monotonic()
        encode_value(value, codec_options)
        costs.append(time.monotonic() - start)
    return tuple(costs)


@dataclass(frozen=True, slots=True)
class OversizedResultSavingsMeasurement:
    prefix_length: NonNegativeInt
    prefix_costs_seconds: tuple[float, ...]
    full_costs_seconds: tuple[float, ...]
    acceptable_savings_threshold_seconds: float

    def __post_init__(self) -> None:
        if self.acceptable_savings_threshold_seconds < 0:
            message = "acceptable_savings_threshold_seconds must not be negative"
            raise BenchmarkConfigurationError(message)

    @property
    def prefix_cost_seconds(self) -> float:
        return statistics.median(self.prefix_costs_seconds)

    @property
    def full_cost_seconds(self) -> float:
        return statistics.median(self.full_costs_seconds)

    @property
    def savings_seconds(self) -> float:
        return self.full_cost_seconds - self.prefix_cost_seconds

    @property
    def meets_acceptable_savings_threshold(self) -> bool:
        return self.savings_seconds >= self.acceptable_savings_threshold_seconds


def measure_oversized_result_savings(
    documents: Sequence[Mapping[str, object]],
    *,
    max_entry_bytes: PositiveInt,
    codec_options: CodecOptions[Any] | None = None,
    repetitions: PositiveInt,
    acceptable_savings_threshold_seconds: float,
) -> OversizedResultSavingsMeasurement:
    prefix_length = find_crossover_prefix_length(
        documents, max_entry_bytes=max_entry_bytes, codec_options=codec_options
    )
    prefix = list(documents[:prefix_length])
    prefix_costs = time_encoder_invocations(
        prefix, codec_options=codec_options, repetitions=repetitions
    )
    full_costs = time_encoder_invocations(
        list(documents), codec_options=codec_options, repetitions=repetitions
    )
    return OversizedResultSavingsMeasurement(
        prefix_length=prefix_length,
        prefix_costs_seconds=prefix_costs,
        full_costs_seconds=full_costs,
        acceptable_savings_threshold_seconds=acceptable_savings_threshold_seconds,
    )


@dataclass(frozen=True, slots=True)
class OversizedResultWorkloadMeasurement:
    end_to_end_cost_seconds: float
    savings: OversizedResultSavingsMeasurement

    def __post_init__(self) -> None:
        if self.end_to_end_cost_seconds < 0:
            message = "end_to_end_cost_seconds must not be negative"
            raise BenchmarkConfigurationError(message)


def measure_oversized_result_workload(
    perform_find: Callable[[], Sequence[Mapping[str, object]]],
    *,
    max_entry_bytes: PositiveInt,
    codec_options: CodecOptions[Any] | None = None,
    repetitions: PositiveInt,
    acceptable_savings_threshold_seconds: float,
) -> OversizedResultWorkloadMeasurement:
    start = time.monotonic()
    documents = perform_find()  # pytriage: TR5 (kept apart to time perform_find alone)
    end_to_end_cost_seconds = time.monotonic() - start
    savings = measure_oversized_result_savings(
        documents,
        max_entry_bytes=max_entry_bytes,
        codec_options=codec_options,
        repetitions=repetitions,
        acceptable_savings_threshold_seconds=acceptable_savings_threshold_seconds,
    )
    return OversizedResultWorkloadMeasurement(
        end_to_end_cost_seconds=end_to_end_cost_seconds, savings=savings
    )
