from __future__ import annotations

import gc
import logging
import threading
import time
import tracemalloc
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest

from client_query_cache import CacheConfigurationError
from client_query_cache._core.collection_metadata import (
    CollectionMetadata,
    CollectionMetadataCache,
)
from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.lru import WeightedLru
from client_query_cache._core.manager import CacheCore, CacheCoreConfig
from client_query_cache._core.namespace_metadata import NamespaceMetadataCache
from client_query_cache._core.snapshots import BypassReason
from client_query_cache._core.unique_keys import (
    UniqueKeyMetadata,
    UniqueKeyMetadataCache,
)
from client_query_cache._shared_index import LocalCacheCore as NativeCacheCore
from client_query_cache._shared_index import SharedOwnerCore
from client_query_cache._types import NonNegativeInt, PositiveFloat, PositiveInt

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterator

    from faker import Faker

    from client_query_cache._core.contracts import LocalCacheCore
    from client_query_cache._core.entries import CacheEntry
    from client_query_cache._core.keys import CacheKey
    from client_query_cache._core.namespace import NamespaceState

pytestmark = pytest.mark.unit
_PROBE_TTL_SECONDS = 30.0
_SHORT_PROBE_TTL_SECONDS = 0.05

_NAMESPACE_LIMIT: PositiveInt = 4
_NAMES_PER_ROUND: PositiveInt = 1_000


@contextmanager
def _trace_python_allocations() -> Generator[None]:
    tracemalloc.start()
    try:
        yield
    finally:
        tracemalloc.stop()


@contextmanager
def _pause_eviction_cleanup(
    core: CacheCore, monkeypatch: pytest.MonkeyPatch
) -> Generator[tuple[threading.Event, threading.Event]]:
    cleanup_started = threading.Event()
    resume_cleanup = threading.Event()
    original_process_evicted = CacheCore._process_evicted

    def pause_process_evicted(instance: CacheCore, entries: list[CacheEntry]) -> None:
        assert instance is core
        assert entries
        cleanup_started.set()
        resume_cleanup.wait()
        original_process_evicted(instance, entries)

    monkeypatch.setattr(type(core), "_process_evicted", pause_process_evicted)
    try:
        yield cleanup_started, resume_cleanup
    finally:
        resume_cleanup.set()


@contextmanager
def _pause_registered_namespace_lookup(
    core: CacheCore, monkeypatch: pytest.MonkeyPatch
) -> Generator[tuple[threading.Event, threading.Event]]:
    lookup_complete = threading.Event()
    resume_lookup = threading.Event()
    original_registered_namespace = CacheCore._registered_namespace

    def pause_registered_namespace(
        instance: CacheCore, namespace: NamespaceId
    ) -> NamespaceState | None:
        state = original_registered_namespace(instance, namespace)
        assert instance is core
        if not lookup_complete.is_set():
            lookup_complete.set()
            assert resume_lookup.wait(5)
        return state

    monkeypatch.setattr(CacheCore, "_registered_namespace", pause_registered_namespace)
    try:
        yield lookup_complete, resume_lookup
    finally:
        resume_lookup.set()


@pytest.mark.parametrize(
    "limit",
    [
        pytest.param(0, id="zero"),
        pytest.param(-1, id="negative"),
        pytest.param(True, id="boolean"),
        pytest.param(1.0, id="float"),
    ],
)
def test_cache_core_rejects_invalid_namespace_limits(limit: object) -> None:
    with pytest.raises(CacheConfigurationError, match="max_namespaces"):
        CacheCoreConfig(max_namespaces=limit)  # type: ignore[arg-type]


def test_namespace_capacity_bypasses_without_retaining_overflow_state() -> None:
    core = CacheCore(CacheCoreConfig(max_namespaces=1))
    tracked = NamespaceId("catalogue", "products")
    overflow = NamespaceId("catalogue", "events")
    assert core.try_current_epoch(tracked) is not None

    assert core.try_current_epoch(overflow) is None
    assert core.current_index_generation(overflow) == 0
    core.record_index_change(overflow)
    core.drop_namespace(overflow)
    core.clear_namespace(overflow)
    identity_capture = core.begin_identity_admission(overflow, "overflow")
    identity_capture.release()
    capture = core.capture_namespace_generation(overflow)
    outcome = core.admit_namespace(capture, "all", [{"_id": 1}])

    assert outcome is AdmissionOutcome.DECLINED_STALE
    assert not core.has_namespace(overflow)
    assert len(core._namespaces) == 1
    assert BypassReason.NAMESPACE_CAPACITY.value == "namespace_capacity"


def test_drop_releases_capacity_and_rejects_a_capture_from_the_previous_lifetime() -> (
    None
):
    core = CacheCore(CacheCoreConfig(max_namespaces=1))
    namespace = NamespaceId("catalogue", "products")
    old_capture = core.capture_namespace_generation(namespace)
    assert core.admit_namespace(old_capture, "all", [{"revision": "old"}]) is (
        AdmissionOutcome.ADMITTED
    )

    core.drop_namespace(namespace)

    assert not core.has_namespace(namespace)
    assert len(core._namespaces) == 0
    new_capture = core.capture_namespace_generation(namespace)
    assert new_capture.generation > old_capture.generation
    assert core.admit_namespace(old_capture, "all", [{"revision": "stale"}]) is (
        AdmissionOutcome.DECLINED_STALE
    )
    assert core.admit_namespace(new_capture, "all", [{"revision": "new"}]) is (
        AdmissionOutcome.ADMITTED
    )
    assert core.lookup_namespace(namespace, "all").value == [{"revision": "new"}]


@pytest.fixture
def make_owner() -> Iterator[Callable[..., SharedOwnerCore]]:
    owners: list[SharedOwnerCore] = []

    def create(
        *databases: str,
        namespaces: PositiveInt = 1,
        probe_ttl_seconds: PositiveFloat = _PROBE_TTL_SECONDS,
    ) -> SharedOwnerCore:
        owner = SharedOwnerCore(
            CacheCoreConfig(max_namespaces=namespaces),
            None,
            list(databases or ("catalogue",)),
            namespaces,
            probe_ttl_seconds,
        )
        owners.append(owner)
        return owner

    yield create
    for owner in owners:
        owner.close()


@pytest.fixture
def owner(make_owner: Callable[..., SharedOwnerCore]) -> SharedOwnerCore:
    return make_owner()


def test_namespace_capacity_check_does_not_register_a_namespace(
    owner: SharedOwnerCore,
) -> None:
    namespace = NamespaceId("catalogue", "products")
    other = NamespaceId("catalogue", "orders")

    assert owner.can_register_namespace(namespace)
    probe_token = owner.begin_namespace_metadata_probe(namespace)
    assert probe_token is not None
    owner.capture_namespace_generation(namespace)
    owner.cancel_namespace_metadata_probe(namespace, probe_token)

    assert owner.can_register_namespace(namespace)
    assert not owner.can_register_namespace(other)
    assert owner.begin_namespace_metadata_probe(other) is None
    assert owner.namespace_metadata_after_probe(other, 0) is None
    assert not owner.release_namespace_if_epoch_matches(other, 0)
    owner.close()
    assert not owner.can_register_namespace(namespace)
    assert owner.begin_namespace_metadata_probe(namespace) is None
    assert owner.namespace_metadata_after_probe(namespace, 0) is None


def test_a_metadata_probe_cannot_reuse_a_dropped_namespace(
    owner: SharedOwnerCore,
) -> None:
    namespace = NamespaceId("catalogue", "products")
    assert owner.try_current_epoch(namespace) is not None
    probe_token = owner.begin_namespace_metadata_probe(namespace)
    assert probe_token is not None

    owner.drop_namespace(namespace)

    assert owner.namespace_metadata_after_probe(namespace, probe_token) is None
    assert not owner.has_namespace(namespace)


@pytest.mark.parametrize(
    "lifecycle_change",
    [CacheCore.clear_namespace, CacheCore.create_namespace, CacheCore.drop_namespace],
    ids=["clear", "create", "drop"],
)
def test_namespace_generation_advances_past_local_writes_before_lifecycle_reset(
    lifecycle_change: Callable[[CacheCore, NamespaceId], object],
) -> None:
    core = CacheCore(CacheCoreConfig(max_namespaces=1))
    namespace = NamespaceId("catalogue", "products")
    core.record_write(namespace, "first")
    core.record_write(namespace, "second")
    old_capture = core.capture_namespace_generation(namespace)

    lifecycle_change(core, namespace)

    new_capture = core.capture_namespace_generation(namespace)
    assert new_capture.generation > old_capture.generation
    assert core.admit_namespace(old_capture, "all", [{"revision": "stale"}]) is (
        AdmissionOutcome.DECLINED_STALE
    )


def _probe_tokens(core: SharedOwnerCore) -> dict[NamespaceId, NonNegativeInt]:
    return {
        NamespaceId(database, collection): token
        for database, collection, token, _active in core._probes()
    }


def test_namespace_metadata_probe_cancellation_and_capacity_are_bounded(
    owner: SharedOwnerCore,
) -> None:
    first = NamespaceId("catalogue", "first")
    second = NamespaceId("catalogue", "second")
    first_token = owner.begin_namespace_metadata_probe(first)
    repeated_token = owner.begin_namespace_metadata_probe(first)

    assert first_token is not None
    assert repeated_token == first_token
    assert owner.begin_namespace_metadata_probe(second) is None
    assert len(owner._probes()) == 1

    owner.cancel_namespace_metadata_probe(first, first_token)
    assert len(owner._probes()) == 1
    owner.cancel_namespace_metadata_probe(first, first_token)
    assert not owner._probes()
    assert owner.begin_namespace_metadata_probe(second) is not None


@pytest.mark.parametrize(
    "replace_probe", [False, True], ids=["invalidated", "replaced"]
)
def test_an_invalidated_metadata_probe_is_rejected_without_its_replacement(
    owner: SharedOwnerCore, *, replace_probe: bool
) -> None:
    namespace = NamespaceId("catalogue", "products")
    stale_token = owner.begin_namespace_metadata_probe(namespace)
    assert stale_token is not None
    owner.invalidate_namespace_metadata_probe(namespace)
    active_token = (
        owner.begin_namespace_metadata_probe(namespace) if replace_probe else None
    )

    assert owner.namespace_metadata_after_probe(namespace, stale_token) is None
    owner.cancel_namespace_metadata_probe(namespace, stale_token)

    assert _probe_tokens(owner) == (
        {namespace: active_token} if active_token is not None else {}
    )
    assert active_token != stale_token


def test_database_probe_invalidation_preserves_probes_for_other_databases(
    make_owner: Callable[..., SharedOwnerCore],
) -> None:
    core = make_owner("catalogue", "archive", namespaces=2)
    affected = NamespaceId("catalogue", "products")
    unaffected = NamespaceId("archive", "products")
    affected_token = core.begin_namespace_metadata_probe(affected)
    unaffected_token = core.begin_namespace_metadata_probe(unaffected)
    assert affected_token is not None
    assert unaffected_token is not None

    core.invalidate_namespace_metadata_probes_for_database("catalogue")

    assert _probe_tokens(core) == {unaffected: unaffected_token}


def test_metadata_probe_is_rejected_when_capacity_fills_after_preflight(
    owner: SharedOwnerCore,
) -> None:
    probed = NamespaceId("catalogue", "probed")
    registered = NamespaceId("catalogue", "registered")
    probe_token = owner.begin_namespace_metadata_probe(probed)
    assert probe_token is not None
    assert owner.try_current_epoch(registered) is not None

    assert owner.namespace_metadata_after_probe(probed, probe_token) is None

    assert not owner.has_namespace(probed)
    assert not owner._probes()


def test_expired_namespace_metadata_probe_does_not_block_another_namespace(
    make_owner: Callable[..., SharedOwnerCore],
) -> None:
    core = make_owner(probe_ttl_seconds=_SHORT_PROBE_TTL_SECONDS)
    first = NamespaceId("catalogue", "first")
    second = NamespaceId("catalogue", "second")
    stale_token = core.begin_namespace_metadata_probe(first)
    assert stale_token is not None

    time.sleep(_SHORT_PROBE_TTL_SECONDS * 2)
    active_token = core.begin_namespace_metadata_probe(second)

    assert active_token is not None
    assert core.namespace_metadata_after_probe(first, stale_token) is None
    assert core.namespace_metadata_after_probe(second, active_token) is not None


def test_stale_ineligibility_probe_cannot_release_a_recreated_namespace(
    owner: SharedOwnerCore,
) -> None:
    namespace = NamespaceId("catalogue", "products")
    old_epoch = owner.try_current_epoch(namespace)
    assert old_epoch is not None

    owner.drop_namespace(namespace)
    new_epoch = owner.try_current_epoch(namespace)
    assert new_epoch is not None

    assert not owner.release_namespace_if_epoch_matches(namespace, old_epoch)
    assert owner.registered_namespace_metadata(namespace) == (
        new_epoch,
        owner.current_index_generation(namespace),
    )


def test_delayed_eviction_cleanup_does_not_resurrect_a_dropped_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = CacheCore(
        CacheCoreConfig(shared_budget_bytes=512, max_entry_bytes=512, max_namespaces=2)
    )
    dropped = NamespaceId("catalogue", "dropped")
    active = NamespaceId("catalogue", "active")
    replacement = NamespaceId("catalogue", "replacement")
    assert (
        core.admit_namespace(
            core.capture_namespace_generation(dropped), "all", {"payload": "a" * 350}
        )
        is AdmissionOutcome.ADMITTED
    )
    active_capture = core.capture_namespace_generation(active)
    outcomes: list[AdmissionOutcome] = []

    with _pause_eviction_cleanup(core, monkeypatch) as (
        cleanup_started,
        resume_cleanup,
    ):
        admission = threading.Thread(
            target=lambda: outcomes.append(
                core.admit_namespace(active_capture, "all", {"payload": "b" * 350})
            )
        )
        admission.start()
        assert cleanup_started.wait(5)

        core.drop_namespace(dropped)
        assert not core.has_namespace(dropped)
        resume_cleanup.set()
        admission.join(5)

    assert not admission.is_alive()
    assert outcomes == [AdmissionOutcome.ADMITTED]
    assert core.try_current_epoch(replacement) is not None
    assert not core.has_namespace(dropped)
    assert len(core._namespaces) == 2


@pytest.mark.parametrize(
    ("entry_kind", "drop_namespace"),
    [
        pytest.param("namespace", False, id="stale-namespace-entry"),
        pytest.param("identity", False, id="stale-identity-entry"),
        pytest.param("namespace", True, id="released-state"),
    ],
)
def test_eviction_cleanup_ignores_entries_from_an_invalidated_namespace_state(
    entry_kind: str,
    drop_namespace: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = CacheCore(CacheCoreConfig(max_namespaces=1))
    namespace = NamespaceId("catalogue", "products")
    if entry_kind == "namespace":
        namespace_capture = core.capture_namespace_generation(namespace)
        outcome = core.admit_namespace(namespace_capture, "all", {"revision": "old"})
    else:
        identity_capture = core.begin_identity_admission(namespace, "product-1")
        outcome = core.admit_identity(identity_capture, "full", {"revision": "old"})
    assert outcome is AdmissionOutcome.ADMITTED

    state = core._namespace(namespace)
    entry = next(iter(state.entry_index))
    key = state.entry_index[entry]
    assert core._lru.remove_exact(key, entry)

    with _pause_registered_namespace_lookup(core, monkeypatch) as (
        lookup_complete,
        resume_lookup,
    ):
        cleanup = threading.Thread(target=core._process_evicted, args=([entry],))
        cleanup.start()
        assert lookup_complete.wait(5)
        if drop_namespace:
            core.drop_namespace(namespace)
        else:
            core.clear_namespace(namespace)
        resume_lookup.set()
        cleanup.join(5)

    assert not cleanup.is_alive()
    if drop_namespace:
        assert not core.has_namespace(namespace)
    else:
        assert core.has_namespace(namespace)
        assert not core.lookup_namespace(namespace, "all").hit


def test_namespace_metadata_cache_evicts_the_oldest_name() -> None:
    metadata = NamespaceMetadataCache[str](2)
    first = NamespaceId("catalogue", "first")
    second = NamespaceId("catalogue", "second")
    third = NamespaceId("catalogue", "third")
    metadata.store(first, "first metadata")
    metadata.store(second, "second metadata")
    assert metadata.find(first) == "first metadata"

    metadata.store(third, "third metadata")

    assert metadata.find(first) is None
    assert metadata.find(second) == "second metadata"
    assert metadata.find(third) == "third metadata"


def test_namespace_metadata_cache_removes_names_and_databases() -> None:
    metadata = NamespaceMetadataCache[str](3)
    first = NamespaceId("catalogue", "first")
    second = NamespaceId("catalogue", "second")
    other_database = NamespaceId("archive", "first")
    metadata.store(first, "first metadata")
    metadata.store(second, "second metadata")
    metadata.store(other_database, "archive metadata")

    assert metadata.remove(first)
    assert not metadata.remove(first)
    metadata.remove_database("catalogue")

    assert metadata.find(first) is None
    assert metadata.find(second) is None
    assert metadata.find(other_database) == "archive metadata"


def test_namespace_metadata_cache_rejects_a_write_after_concurrent_invalidation() -> (
    None
):
    metadata = CollectionMetadataCache(1)
    namespace = NamespaceId("catalogue", "products")
    stale_metadata = CollectionMetadata(
        checked_epoch=0,
        bypass_reason=BypassReason.VIEW_COLLECTION,
        default_collation=None,
        epoch_bound=False,
    )
    captured_version = metadata.version
    store_ready = threading.Barrier(2)
    resume_store = threading.Barrier(2)
    stored: list[bool] = []

    def store_late_metadata() -> None:
        store_ready.wait(5)
        resume_store.wait(5)
        stored.append(
            metadata.put_if_version(namespace, stale_metadata, captured_version)
        )

    store = threading.Thread(target=store_late_metadata)
    store.start()
    store_ready.wait(5)
    assert not metadata.remove(namespace)
    resume_store.wait(5)
    store.join(5)

    assert not store.is_alive()
    assert stored == [False]
    assert metadata.find(namespace) is None


def test_namespace_metadata_cache_accepts_a_probe_after_an_unrelated_store() -> None:
    metadata = NamespaceMetadataCache[str](2)
    probed_namespace = NamespaceId("catalogue", "probed")
    unrelated_namespace = NamespaceId("catalogue", "unrelated")
    captured_version = metadata.version  # pytriage: TR5 (snapshot before the store)

    metadata.store(unrelated_namespace, "unrelated metadata")

    assert metadata.put_if_version(
        probed_namespace,
        "probed metadata",
        captured_version,
    )
    assert metadata.find(probed_namespace) == "probed metadata"


def test_storing_metadata_again_refreshes_its_position_before_eviction() -> None:
    metadata = NamespaceMetadataCache[str](2)
    first = NamespaceId("catalogue", "first")
    second = NamespaceId("catalogue", "second")
    third = NamespaceId("catalogue", "third")
    metadata.store(first, "first metadata")
    metadata.store(second, "second metadata")

    metadata.store(first, "refreshed metadata")
    metadata.store(third, "third metadata")

    assert metadata.find(first) == "refreshed metadata"
    assert metadata.find(second) is None
    assert metadata.find(third) == "third metadata"


def test_namespace_metadata_reaches_a_memory_plateau_under_name_churn(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="client_query_cache._core.manager")
    with _trace_python_allocations():
        core = CacheCore(CacheCoreConfig(max_namespaces=_NAMESPACE_LIMIT))
        collection_metadata = CollectionMetadataCache(_NAMESPACE_LIMIT)
        unique_key_metadata = UniqueKeyMetadataCache(_NAMESPACE_LIMIT)
        retained_bytes: list[NonNegativeInt] = []

        for round_number in range(4):
            for namespace_number in range(_NAMES_PER_ROUND):
                namespace = NamespaceId(
                    "catalogue", f"events_{round_number}_{namespace_number}"
                )
                epoch = core.try_current_epoch(namespace)
                assert epoch is not None
                core.record_write(namespace, namespace_number)
                collection_metadata.put(
                    namespace,
                    CollectionMetadata(
                        checked_epoch=epoch,
                        bypass_reason=None,
                        default_collation=None,
                    ),
                )
                unique_key_metadata.put(
                    namespace,
                    UniqueKeyMetadata(
                        checked_index_generation=core.current_index_generation(
                            namespace
                        ),
                        keys=(),
                    ),
                )
                core.drop_namespace(namespace)

            gc.collect()
            retained_bytes.append(tracemalloc.get_traced_memory()[0])

    assert len(core._namespaces) == 0
    assert len(collection_metadata._entries) == _NAMESPACE_LIMIT
    assert len(unique_key_metadata._entries) == _NAMESPACE_LIMIT
    assert all(current <= retained_bytes[0] + 16_384 for current in retained_bytes[1:])


@pytest.mark.parametrize(
    "factory", [CacheCore, NativeCacheCore], ids=["reference", "native"]
)
def test_namespace_registration_capacity_and_epoch_release(
    factory: type[LocalCacheCore],
) -> None:
    core = factory(CacheCoreConfig(max_namespaces=1))
    registered = NamespaceId("catalogue", "products")
    other = NamespaceId("catalogue", "orders")
    assert core.can_register_namespace(registered)
    epoch = core.try_current_epoch(registered)
    assert epoch is not None

    assert core.can_register_namespace(registered)
    assert not core.can_register_namespace(other)
    assert core.is_database_available(registered.database)
    assert not core.release_namespace_if_epoch_matches(other, epoch)
    assert not core.release_namespace_if_epoch_matches(registered, epoch + 1)
    assert core.release_namespace_if_epoch_matches(registered, epoch)
    assert core.can_register_namespace(other)
    core.close()
    assert not core.can_register_namespace(registered)


def test_namespace_release_tolerates_close_clearing_its_registry(
    monkeypatch: pytest.MonkeyPatch, faker: Faker
) -> None:
    core = CacheCore()
    namespace = NamespaceId("catalogue", "products")
    capture = core.capture_namespace_generation(namespace)
    assert core.admit_namespace(capture, "all", faker.pystr()) is (
        AdmissionOutcome.ADMITTED
    )
    remove_exact = WeightedLru.remove_exact

    def close_while_releasing(
        lru: WeightedLru, key: CacheKey, entry: CacheEntry
    ) -> bool:
        core.close()
        return remove_exact(lru, key, entry)

    monkeypatch.setattr(WeightedLru, "remove_exact", close_while_releasing)
    core.drop_namespace(namespace)

    assert not core.has_namespace(namespace)
