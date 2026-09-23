from __future__ import annotations

import enum
import random
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from benchmarks.stream_cost.errors import (
    BenchmarkConfigurationError,
    BenchmarkSetupError,
)
from benchmarks.stream_cost.generators import (
    LARGE_DOCUMENT_PROFILE,
    MEDIUM_DOCUMENT_PROFILE,
    SMALL_DOCUMENT_PROFILE,
    DocumentSizeProfile,
    generate_seeded_documents,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from typing import Any

    from pymongo.synchronous.collection import Collection

    from mongo_client_cache._core.snapshots import CacheSnapshot
    from mongo_client_cache.synchronous.collection import CachedCollection

# A read repeated twice against the identical cache key always misses (and
# admits) on the first call and hits on the second, satisfying the
# admission-and-hit priming requirement without depending on data contents.
_WARMUP_READ_REPEATS = 2


class WorkloadKind(enum.Enum):
    IDLE = "idle"
    READ_HEAVY = "read_heavy"
    BALANCED = "balanced"
    WRITE_DOMINANT = "write_dominant"


@dataclass(frozen=True, slots=True)
class OperationCounts:
    reads: int
    writes: int

    def __post_init__(self) -> None:
        if self.reads < 0:
            message = "reads must not be negative"
            raise BenchmarkConfigurationError(message)
        if self.writes < 0:
            message = "writes must not be negative"
            raise BenchmarkConfigurationError(message)


DATA_SIZE_PROFILES: tuple[DocumentSizeProfile, ...] = (
    SMALL_DOCUMENT_PROFILE,
    MEDIUM_DOCUMENT_PROFILE,
    LARGE_DOCUMENT_PROFILE,
)

_SAMPLING_OPERATIONS_BY_KIND: dict[WorkloadKind, OperationCounts] = {
    WorkloadKind.IDLE: OperationCounts(reads=0, writes=0),
    WorkloadKind.READ_HEAVY: OperationCounts(reads=100, writes=10),
    WorkloadKind.BALANCED: OperationCounts(reads=50, writes=50),
    WorkloadKind.WRITE_DOMINANT: OperationCounts(reads=10, writes=100),
}

_DEFAULT_DOCUMENT_COUNT = 100


@dataclass(frozen=True, slots=True)
class WorkloadVariant:
    kind: WorkloadKind
    data_size: DocumentSizeProfile
    document_count: int
    warmup: OperationCounts
    sampling: OperationCounts
    seed: int

    def __post_init__(self) -> None:
        if self.document_count <= 0:
            message = "document_count must be positive"
            raise BenchmarkConfigurationError(message)
        if self.warmup.reads < _WARMUP_READ_REPEATS:
            message = (
                f"warmup.reads ({self.warmup.reads}) must be at least "
                f"{_WARMUP_READ_REPEATS} to exercise both an admission and a hit"
            )
            raise BenchmarkConfigurationError(message)

    @property
    def name(self) -> str:
        return f"{self.kind.value}-{self.data_size.name}"


def _standard_variant(
    kind: WorkloadKind, data_size: DocumentSizeProfile, *, seed: int
) -> WorkloadVariant:
    return WorkloadVariant(
        kind=kind,
        data_size=data_size,
        document_count=_DEFAULT_DOCUMENT_COUNT,
        warmup=OperationCounts(reads=_WARMUP_READ_REPEATS, writes=0),
        sampling=_SAMPLING_OPERATIONS_BY_KIND[kind],
        seed=seed,
    )


STANDARD_WORKLOAD_VARIANTS: tuple[WorkloadVariant, ...] = tuple(
    _standard_variant(kind, data_size, seed=index)
    for index, (kind, data_size) in enumerate(
        (kind, data_size) for kind in WorkloadKind for data_size in DATA_SIZE_PROFILES
    )
)


@dataclass(frozen=True, slots=True)
class SeededDataset:
    documents: tuple[dict[str, object], ...]

    @property
    def ids(self) -> tuple[object, ...]:
        return tuple(document["_id"] for document in self.documents)


def seed_dataset(variant: WorkloadVariant) -> SeededDataset:
    documents = generate_seeded_documents(
        variant.data_size, count=variant.document_count, seed=variant.seed
    )
    return SeededDataset(documents=tuple(documents))


def insert_dataset(
    collection: Collection[dict[str, Any]], dataset: SeededDataset
) -> None:
    if not dataset.documents:
        message = "dataset must not be empty"
        raise BenchmarkConfigurationError(message)
    collection.insert_many(list(dataset.documents))


def sample_operation_ids(
    dataset: SeededDataset, count: int, *, seed: int
) -> tuple[object, ...]:
    if count == 0:
        return ()
    rng = random.Random(seed)
    return tuple(rng.choice(dataset.ids) for _ in range(count))


@dataclass(frozen=True, slots=True)
class PrimingDelta:
    admissions: int
    hits: int


def priming_delta(before: CacheSnapshot, after: CacheSnapshot) -> PrimingDelta:
    return PrimingDelta(
        admissions=after.entry_count - before.entry_count,
        hits=after.hits - before.hits,
    )


def verify_primed(
    before: CacheSnapshot, after: CacheSnapshot, *, variant_name: str
) -> None:
    delta = priming_delta(before, after)
    if delta.admissions <= 0 or delta.hits <= 0:
        message = (
            f"workload variant {variant_name!r} was not primed through the normal "
            f"cache admission path before sampling: admission delta="
            f"{delta.admissions}, hit delta={delta.hits}"
        )
        raise BenchmarkSetupError(message)


def verify_oversized_primed(
    before: CacheSnapshot, after: CacheSnapshot, *, variant_name: str
) -> None:
    delta = after.oversized_bypasses - before.oversized_bypasses
    if delta <= 0:
        message = (
            f"oversized-result workload variant {variant_name!r} did not record a "
            f"positive oversized-bypass counter delta during warmup (delta={delta})"
        )
        raise BenchmarkSetupError(message)


def prime_read_variant(
    read_once: Callable[[], object], *, repeats: int = _WARMUP_READ_REPEATS
) -> None:
    if repeats < _WARMUP_READ_REPEATS:
        message = (
            f"repeats ({repeats}) must be at least {_WARMUP_READ_REPEATS} to "
            "exercise both an admission and a hit"
        )
        raise BenchmarkConfigurationError(message)
    for _ in range(repeats):
        read_once()


def assert_identical_results(
    raw_value: object, cache_value: object, *, variant_name: str
) -> None:
    if raw_value != cache_value:
        message = (
            f"workload variant {variant_name!r} returned different data for the "
            "raw and cache variants"
        )
        raise BenchmarkSetupError(message)


def assert_identical_workload_parameters(
    raw_parameters: Mapping[str, object],
    cache_parameters: Mapping[str, object],
    *,
    variant_name: str,
) -> None:
    if dict(raw_parameters) != dict(cache_parameters):
        message = (
            f"workload variant {variant_name!r} used different parameters for the "
            "raw and cache variants"
        )
        raise BenchmarkConfigurationError(message)


@dataclass(frozen=True, slots=True)
class PairedReadOutcome:
    variant: WorkloadVariant
    raw_results: tuple[object, ...]
    cache_results: tuple[object, ...]


def run_paired_reads(
    raw_collection: Collection[dict[str, Any]],
    cache_collection: CachedCollection[dict[str, Any]],
    variant: WorkloadVariant,
    ids: Sequence[object],
) -> PairedReadOutcome:
    raw_results = tuple(
        raw_collection.find_one({"_id": document_id}) for document_id in ids
    )
    cache_results = tuple(
        cache_collection.find_one({"_id": document_id}) for document_id in ids
    )
    for raw_value, cache_value in zip(raw_results, cache_results, strict=True):
        assert_identical_results(raw_value, cache_value, variant_name=variant.name)
    return PairedReadOutcome(
        variant=variant, raw_results=raw_results, cache_results=cache_results
    )


def issue_writes(
    collection: Collection[dict[str, Any]],
    dataset: SeededDataset,
    count: int,
    *,
    seed: int,
) -> int:
    ids = sample_operation_ids(dataset, count, seed=seed)
    for document_id in ids:
        collection.update_one({"_id": document_id}, {"$inc": {"touched": 1}})
    return len(ids)


@dataclass(frozen=True, slots=True)
class WorkloadVariantOutcome:
    variant: WorkloadVariant
    reads: PairedReadOutcome
    writes_issued: int


def run_workload_variant(
    raw_collection: Collection[dict[str, Any]],
    cache_collection: CachedCollection[dict[str, Any]],
    variant: WorkloadVariant,
    dataset: SeededDataset,
) -> WorkloadVariantOutcome:
    read_ids = sample_operation_ids(dataset, variant.sampling.reads, seed=variant.seed)
    reads = run_paired_reads(raw_collection, cache_collection, variant, read_ids)
    writes_issued = issue_writes(
        raw_collection, dataset, variant.sampling.writes, seed=variant.seed + 1
    )
    return WorkloadVariantOutcome(
        variant=variant, reads=reads, writes_issued=writes_issued
    )


def time_call[T](call: Callable[[], T]) -> tuple[T, float]:
    start = time.monotonic()
    call_result = call()
    elapsed_seconds = time.monotonic() - start
    return call_result, elapsed_seconds
