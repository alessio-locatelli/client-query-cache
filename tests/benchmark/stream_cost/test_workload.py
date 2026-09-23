from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

from benchmarks.stream_cost.errors import (
    BenchmarkConfigurationError,
    BenchmarkSetupError,
)
from benchmarks.stream_cost.generators import (
    LARGE_DOCUMENT_PROFILE,
    MEDIUM_DOCUMENT_PROFILE,
    SMALL_DOCUMENT_PROFILE,
)
from benchmarks.stream_cost.workload import (
    DATA_SIZE_PROFILES,
    STANDARD_WORKLOAD_VARIANTS,
    OperationCounts,
    SeededDataset,
    WorkloadKind,
    WorkloadVariant,
    assert_identical_results,
    assert_identical_workload_parameters,
    insert_dataset,
    prime_read_variant,
    priming_delta,
    sample_operation_ids,
    seed_dataset,
    time_call,
    verify_oversized_primed,
    verify_primed,
)
from mongo_client_cache._core.snapshots import CacheSnapshot

if TYPE_CHECKING:
    from pymongo.synchronous.collection import Collection

pytestmark = pytest.mark.unit


def _snapshot(
    *,
    entry_count: int = 0,
    hits: int = 0,
    oversized_bypasses: int = 0,
) -> CacheSnapshot:
    return CacheSnapshot(
        lifecycle="active",
        used_bytes=0,
        shared_budget_bytes=1,
        max_entry_bytes=1,
        entry_count=entry_count,
        hits=hits,
        misses=0,
        evictions=0,
        bypasses=0,
        oversized_bypasses=oversized_bypasses,
    )


@pytest.mark.parametrize(
    ("reads", "writes", "match"),
    [
        (-1, 0, "reads"),
        (0, -1, "writes"),
    ],
)
def test_operation_counts_rejects_negative_values(
    reads: int, writes: int, match: str
) -> None:
    with pytest.raises(BenchmarkConfigurationError, match=match):
        OperationCounts(reads=reads, writes=writes)


def test_workload_variant_rejects_non_positive_document_count() -> None:
    with pytest.raises(BenchmarkConfigurationError, match="document_count"):
        WorkloadVariant(
            kind=WorkloadKind.IDLE,
            data_size=SMALL_DOCUMENT_PROFILE,
            document_count=0,
            warmup=OperationCounts(reads=2, writes=0),
            sampling=OperationCounts(reads=0, writes=0),
            seed=1,
        )


def test_workload_variant_rejects_a_warmup_that_cannot_prime_a_hit() -> None:
    with pytest.raises(BenchmarkConfigurationError, match=r"warmup\.reads"):
        WorkloadVariant(
            kind=WorkloadKind.IDLE,
            data_size=SMALL_DOCUMENT_PROFILE,
            document_count=10,
            warmup=OperationCounts(reads=1, writes=0),
            sampling=OperationCounts(reads=0, writes=0),
            seed=1,
        )


def test_standard_workload_variants_cover_every_kind_and_data_size() -> None:
    seen = {(variant.kind, variant.data_size) for variant in STANDARD_WORKLOAD_VARIANTS}
    expected = {
        (kind, data_size) for kind in WorkloadKind for data_size in DATA_SIZE_PROFILES
    }
    assert seen == expected
    assert len(STANDARD_WORKLOAD_VARIANTS) == len(expected)


def test_standard_workload_variants_have_unique_names() -> None:
    names = [variant.name for variant in STANDARD_WORKLOAD_VARIANTS]
    assert len(names) == len(set(names))


def test_idle_variant_has_zero_sampling_operations() -> None:
    idle_variants = [
        variant
        for variant in STANDARD_WORKLOAD_VARIANTS
        if variant.kind is WorkloadKind.IDLE
    ]
    assert idle_variants
    for variant in idle_variants:
        assert variant.sampling == OperationCounts(reads=0, writes=0)
        # An idle variant still primes admission/hit counters before its
        # zero-operation sampling window; "idle" describes the sampling
        # phase, not an exemption from the priming requirement.
        assert variant.warmup.reads >= 2


@pytest.mark.parametrize(
    ("kind", "expect_reads_at_least_writes"),
    [
        (WorkloadKind.READ_HEAVY, True),
        (WorkloadKind.WRITE_DOMINANT, False),
    ],
)
def test_read_heavy_and_write_dominant_variants_skew_as_named(
    kind: WorkloadKind, expect_reads_at_least_writes: bool
) -> None:
    variant = next(
        variant for variant in STANDARD_WORKLOAD_VARIANTS if variant.kind is kind
    )
    if expect_reads_at_least_writes:
        assert variant.sampling.reads > variant.sampling.writes
    else:
        assert variant.sampling.writes > variant.sampling.reads


def test_balanced_variant_has_equal_reads_and_writes() -> None:
    variant = next(
        variant
        for variant in STANDARD_WORKLOAD_VARIANTS
        if variant.kind is WorkloadKind.BALANCED
    )
    assert variant.sampling.reads == variant.sampling.writes


@pytest.mark.parametrize(
    "profile", [SMALL_DOCUMENT_PROFILE, MEDIUM_DOCUMENT_PROFILE, LARGE_DOCUMENT_PROFILE]
)
def test_seed_dataset_is_deterministic_for_a_given_seed(profile: object) -> None:
    variant = WorkloadVariant(
        kind=WorkloadKind.IDLE,
        data_size=profile,  # type: ignore[arg-type]
        document_count=5,
        warmup=OperationCounts(reads=2, writes=0),
        sampling=OperationCounts(reads=0, writes=0),
        seed=42,
    )
    first = seed_dataset(variant)
    second = seed_dataset(variant)
    assert first == second
    assert len(first.documents) == 5
    assert len(first.ids) == 5


def test_insert_dataset_rejects_an_empty_dataset() -> None:
    empty_dataset = SeededDataset(documents=())
    with pytest.raises(BenchmarkConfigurationError, match="dataset must not be empty"):
        insert_dataset(cast("Collection[dict[str, Any]]", None), empty_dataset)


def test_sample_operation_ids_returns_empty_for_zero_count() -> None:
    variant = WorkloadVariant(
        kind=WorkloadKind.IDLE,
        data_size=SMALL_DOCUMENT_PROFILE,
        document_count=3,
        warmup=OperationCounts(reads=2, writes=0),
        sampling=OperationCounts(reads=0, writes=0),
        seed=1,
    )
    assert sample_operation_ids(seed_dataset(variant), 0, seed=1) == ()


def test_sample_operation_ids_is_deterministic_and_drawn_from_the_dataset() -> None:
    variant = WorkloadVariant(
        kind=WorkloadKind.IDLE,
        data_size=SMALL_DOCUMENT_PROFILE,
        document_count=3,
        warmup=OperationCounts(reads=2, writes=0),
        sampling=OperationCounts(reads=0, writes=0),
        seed=7,
    )
    dataset = seed_dataset(variant)
    first = sample_operation_ids(dataset, 10, seed=99)
    second = sample_operation_ids(dataset, 10, seed=99)
    assert first == second
    assert len(first) == 10
    assert set(first) <= set(dataset.ids)


def test_priming_delta_computes_admission_and_hit_deltas() -> None:
    before = _snapshot(entry_count=1, hits=2)
    after = _snapshot(entry_count=2, hits=5)
    delta = priming_delta(before, after)
    assert delta.admissions == 1
    assert delta.hits == 3


@pytest.mark.parametrize(
    ("entry_delta", "hit_delta"),
    [
        (0, 1),
        (1, 0),
        (0, 0),
        (-1, 1),
    ],
)
def test_verify_primed_rejects_non_positive_deltas(
    entry_delta: int, hit_delta: int
) -> None:
    before = _snapshot(entry_count=5, hits=5)
    after = _snapshot(entry_count=5 + entry_delta, hits=5 + hit_delta)
    with pytest.raises(BenchmarkSetupError, match="not primed"):
        verify_primed(before, after, variant_name="read-heavy-small")


def test_verify_primed_accepts_positive_deltas() -> None:
    before = _snapshot(entry_count=0, hits=0)
    after = _snapshot(entry_count=1, hits=1)
    verify_primed(before, after, variant_name="read-heavy-small")


def test_verify_oversized_primed_rejects_a_non_positive_delta() -> None:
    before = _snapshot(oversized_bypasses=0)
    after = _snapshot(oversized_bypasses=0)
    with pytest.raises(BenchmarkSetupError, match="oversized-bypass"):
        verify_oversized_primed(before, after, variant_name="oversized-result")


def test_verify_oversized_primed_accepts_a_positive_delta() -> None:
    before = _snapshot(oversized_bypasses=0)
    after = _snapshot(oversized_bypasses=1)
    verify_oversized_primed(before, after, variant_name="oversized-result")


def test_prime_read_variant_rejects_too_few_repeats() -> None:
    with pytest.raises(BenchmarkConfigurationError, match="repeats"):
        prime_read_variant(lambda: None, repeats=1)


def test_prime_read_variant_invokes_the_read_the_requested_number_of_times() -> None:
    calls: list[None] = []
    prime_read_variant(lambda: calls.append(None), repeats=3)
    assert len(calls) == 3


def test_assert_identical_results_rejects_mismatched_data() -> None:
    with pytest.raises(BenchmarkSetupError, match="different data"):
        assert_identical_results({"a": 1}, {"a": 2}, variant_name="read-heavy-small")


def test_assert_identical_results_accepts_matching_data() -> None:
    assert_identical_results({"a": 1}, {"a": 1}, variant_name="read-heavy-small")


def test_assert_identical_workload_parameters_rejects_mismatched_parameters() -> None:
    with pytest.raises(BenchmarkConfigurationError, match="different parameters"):
        assert_identical_workload_parameters(
            {"reads": 1}, {"reads": 2}, variant_name="read-heavy-small"
        )


def test_assert_identical_workload_parameters_accepts_matching_parameters() -> None:
    assert_identical_workload_parameters(
        {"reads": 1}, {"reads": 1}, variant_name="read-heavy-small"
    )


def test_time_call_returns_the_result_and_a_non_negative_elapsed_time() -> None:
    result, elapsed_seconds = time_call(lambda: 42)
    assert result == 42
    assert elapsed_seconds >= 0
