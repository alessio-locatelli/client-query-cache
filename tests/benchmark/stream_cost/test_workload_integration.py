from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.workload import (
    STANDARD_WORKLOAD_VARIANTS,
    OperationCounts,
    WorkloadKind,
    WorkloadVariant,
    insert_dataset,
    issue_writes,
    prime_read_variant,
    run_paired_reads,
    run_workload_variant,
    sample_operation_ids,
    seed_dataset,
    verify_primed,
)

if TYPE_CHECKING:
    from client_query_cache.synchronous.manager import CacheManager
    from tests.conftest import CollectionName, DatabaseName

pytestmark = pytest.mark.integration


def _read_heavy_small_variant() -> WorkloadVariant:
    return next(
        variant
        for variant in STANDARD_WORKLOAD_VARIANTS
        if variant.kind is WorkloadKind.READ_HEAVY and variant.data_size.name == "small"
    )


def _balanced_small_variant() -> WorkloadVariant:
    return next(
        variant
        for variant in STANDARD_WORKLOAD_VARIANTS
        if variant.kind is WorkloadKind.BALANCED and variant.data_size.name == "small"
    )


def _idle_small_variant() -> WorkloadVariant:
    return next(
        variant
        for variant in STANDARD_WORKLOAD_VARIANTS
        if variant.kind is WorkloadKind.IDLE and variant.data_size.name == "small"
    )


def test_priming_yields_positive_admission_and_hit_deltas(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    persistent_collection_name: CollectionName,
) -> None:
    variant = _read_heavy_small_variant()
    dataset = seed_dataset(variant)
    database = cache_manager[cached_database_name]
    collection = database[persistent_collection_name]
    insert_dataset(collection.raw, dataset)

    document_id = dataset.ids[0]
    before = cache_manager.cache_core.snapshot()
    prime_read_variant(lambda: collection.find_one({"_id": document_id}))
    after = cache_manager.cache_core.snapshot()

    verify_primed(before, after, variant_name=variant.name)


def test_run_paired_reads_returns_identical_data_for_raw_and_cache(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    persistent_collection_name: CollectionName,
) -> None:
    variant = _read_heavy_small_variant()
    dataset = seed_dataset(variant)
    database = cache_manager[cached_database_name]
    collection = database[persistent_collection_name]
    insert_dataset(collection.raw, dataset)

    ids = sample_operation_ids(dataset, 5, seed=1)
    outcome = run_paired_reads(collection.raw, collection, variant, ids)

    assert outcome.raw_results == outcome.cache_results
    assert all(document is not None for document in outcome.raw_results)


def test_issue_writes_updates_the_requested_number_of_seeded_documents(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    persistent_collection_name: CollectionName,
) -> None:
    variant = _read_heavy_small_variant()
    dataset = seed_dataset(variant)
    database = cache_manager[cached_database_name]
    collection = database[persistent_collection_name]
    insert_dataset(collection.raw, dataset)

    written = issue_writes(collection.raw, dataset, 5, seed=2)

    assert written == 5
    touched_count = collection.raw.count_documents({"touched": {"$gte": 1}})
    assert touched_count > 0


def test_run_workload_variant_composes_the_configured_read_write_mix(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    persistent_collection_name: CollectionName,
) -> None:
    variant = _balanced_small_variant()
    dataset = seed_dataset(variant)
    database = cache_manager[cached_database_name]
    collection = database[persistent_collection_name]
    insert_dataset(collection.raw, dataset)

    before = cache_manager.cache_core.snapshot()
    outcome = run_workload_variant(
        cache_manager, collection.raw, collection, variant, dataset
    )
    after = cache_manager.cache_core.snapshot()

    assert outcome.variant is variant
    assert len(outcome.reads.raw_results) == variant.sampling.reads
    assert outcome.reads.raw_results == outcome.reads.cache_results
    assert outcome.writes_issued == variant.sampling.writes
    touched_count = collection.raw.count_documents({"touched": {"$gte": 1}})
    assert touched_count > 0
    assert after.entry_count > before.entry_count
    assert after.hits > before.hits


def test_run_workload_variant_still_primes_the_idle_variant(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    persistent_collection_name: CollectionName,
) -> None:
    variant = _idle_small_variant()
    dataset = seed_dataset(variant)
    database = cache_manager[cached_database_name]
    collection = database[persistent_collection_name]
    insert_dataset(collection.raw, dataset)

    before = cache_manager.cache_core.snapshot()
    outcome = run_workload_variant(
        cache_manager, collection.raw, collection, variant, dataset
    )
    after = cache_manager.cache_core.snapshot()

    assert outcome.reads.raw_results == ()
    assert outcome.reads.cache_results == ()
    assert outcome.writes_issued == 0
    assert after.entry_count > before.entry_count
    assert after.hits > before.hits


def test_run_workload_variant_executes_configured_warmup_writes(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    persistent_collection_name: CollectionName,
) -> None:
    base_variant = _idle_small_variant()
    variant = WorkloadVariant(
        kind=base_variant.kind,
        data_size=base_variant.data_size,
        document_count=base_variant.document_count,
        warmup=OperationCounts(reads=2, writes=3),
        sampling=base_variant.sampling,
        seed=base_variant.seed,
    )
    dataset = seed_dataset(variant)
    database = cache_manager[cached_database_name]
    collection = database[persistent_collection_name]
    insert_dataset(collection.raw, dataset)

    run_workload_variant(cache_manager, collection.raw, collection, variant, dataset)

    touched_count = collection.raw.count_documents({"touched": {"$gte": 1}})
    assert touched_count > 0


def test_run_paired_reads_rejects_mismatched_raw_and_cache_data(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    persistent_collection_name: CollectionName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    variant = _read_heavy_small_variant()
    dataset = seed_dataset(variant)
    database = cache_manager[cached_database_name]
    collection = database[persistent_collection_name]
    insert_dataset(collection.raw, dataset)

    mismatched_raw_collection = database.raw[nonpersistent_collection_name]
    mismatched_documents = [dict(document) for document in dataset.documents]
    for document in mismatched_documents:
        document["padding"] = "mismatched"
    mismatched_raw_collection.insert_many(mismatched_documents)

    with pytest.raises(BenchmarkSetupError, match="different data"):
        run_paired_reads(
            mismatched_raw_collection, collection, variant, (dataset.ids[0],)
        )
