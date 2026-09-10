from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import pytest

from mongo_client_cache._core.canonical import canonicalize
from mongo_client_cache._core.codec import encode_value
from mongo_client_cache._core.entries import AdmissionOutcome, CacheEntry
from mongo_client_cache._core.errors import UnsupportedCacheRequestError
from mongo_client_cache._core.keys import IdentityCacheKey, NamespaceId
from mongo_client_cache._core.locking import LockOrderViolationError
from mongo_client_cache._core.manager import CacheCore, CacheCoreConfig
from tests.core.conftest import (
    patch_conditional_put_hook as _patch_conditional_put_hook,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from mongo_client_cache._core.keys import CacheKey
    from mongo_client_cache._core.lru import WeightedLru

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "invoke",
    [
        pytest.param(
            lambda core, namespace: core.begin_identity_admission(namespace, {1, 2, 3}),
            id="identity_admission_unsupported_identity",
        ),
        pytest.param(
            lambda core, namespace: core.admit_identity(
                core.begin_identity_admission(namespace, "doc-1"),
                {1, 2, 3},
                {"a": 1},
            ),
            id="identity_admission_unsupported_read_shape",
        ),
        pytest.param(
            lambda core, namespace: core.admit_namespace(
                core.capture_namespace_generation(namespace), {1, 2, 3}, []
            ),
            id="namespace_admission_unsupported_discriminator",
        ),
    ],
)
def test_admission_rejects_unsupported_canonicalization_input(
    core: CacheCore,
    namespace: NamespaceId,
    invoke: Callable[[CacheCore, NamespaceId], object],
) -> None:
    with pytest.raises(UnsupportedCacheRequestError):
        invoke(core, namespace)


def test_identity_admission_rejects_none_as_an_identity_value(
    core: CacheCore, namespace: NamespaceId
) -> None:
    with pytest.raises(UnsupportedCacheRequestError):
        core.begin_identity_admission(namespace, None)


def test_admission_rejects_an_oversize_value(namespace: NamespaceId) -> None:
    core = CacheCore(CacheCoreConfig(shared_budget_bytes=1_000, max_entry_bytes=32))
    capture = core.begin_identity_admission(namespace, "doc-1")
    outcome = core.admit_identity(capture, "full", {"payload": "x" * 100})
    assert outcome is AdmissionOutcome.DECLINED_OVERSIZE


@pytest.mark.parametrize(
    "trigger_before_insert",
    [
        pytest.param(False, id="rollback_after_physical_insert"),
        pytest.param(True, id="late_stale_insertion_before_physical_insert"),
    ],
)
def test_a_racing_fresher_admission_wins_regardless_of_when_it_lands(
    core: CacheCore,
    namespace: NamespaceId,
    monkeypatch: pytest.MonkeyPatch,
    trigger_before_insert: bool,
) -> None:
    identity = "doc-1"
    read_shape = "full"
    capture_stale = core.begin_identity_admission(namespace, identity)
    triggered = False

    def hook(_key: CacheKey, entry: CacheEntry) -> None:
        nonlocal triggered
        if triggered or entry.generation_key != capture_stale.generation_key:
            return
        triggered = True
        core.record_write(namespace, identity)
        fresh_capture = core.begin_identity_admission(namespace, identity)
        outcome = core.admit_identity(fresh_capture, read_shape, {"v": "fresh"})
        assert outcome is AdmissionOutcome.ADMITTED

    _patch_conditional_put_hook(
        monkeypatch, core, hook, trigger_before_insert=trigger_before_insert
    )

    outcome = core.admit_identity(capture_stale, read_shape, {"v": "stale"})

    assert outcome is AdmissionOutcome.DECLINED_STALE
    result = core.lookup_identity(namespace, identity, read_shape)
    assert result.hit
    assert result.value == {"v": "fresh"}


@pytest.mark.parametrize(
    "trigger_before_insert",
    [
        pytest.param(False, id="rollback_after_physical_insert"),
        pytest.param(True, id="late_stale_insertion_before_physical_insert"),
    ],
)
def test_a_racing_fresher_namespace_admission_wins_regardless_of_when_it_lands(
    core: CacheCore,
    namespace: NamespaceId,
    monkeypatch: pytest.MonkeyPatch,
    trigger_before_insert: bool,
) -> None:
    discriminator = ("find", "shape")
    capture_stale = core.capture_namespace_generation(namespace)
    triggered = False

    def hook(_key: CacheKey, entry: CacheEntry) -> None:
        nonlocal triggered
        if triggered or entry.generation_key != (capture_stale.generation,):
            return
        triggered = True
        core.record_write(namespace, "some-doc")
        fresh_capture = core.capture_namespace_generation(namespace)
        outcome = core.admit_namespace(fresh_capture, discriminator, ["fresh"])
        assert outcome is AdmissionOutcome.ADMITTED

    _patch_conditional_put_hook(
        monkeypatch, core, hook, trigger_before_insert=trigger_before_insert
    )

    outcome = core.admit_namespace(capture_stale, discriminator, ["stale"])

    assert outcome is AdmissionOutcome.DECLINED_STALE
    result = core.lookup_namespace(namespace, discriminator)
    assert result.hit
    assert result.value == ["fresh"]


_BEGIN_AND_ADMIT_BY_KIND = [
    pytest.param(
        lambda core, namespace: core.begin_identity_admission(namespace, "doc-1"),
        lambda core, capture: core.admit_identity(capture, "full", {"v": "x"}),
        id="identity_guarded",
    ),
    pytest.param(
        lambda core, namespace: core.capture_namespace_generation(namespace),
        lambda core, capture: core.admit_namespace(capture, ("find", {}), ["x"]),
        id="namespace_guarded",
    ),
]


@pytest.mark.parametrize(("begin", "admit"), _BEGIN_AND_ADMIT_BY_KIND)
def test_an_entry_evicted_before_publication_is_not_indexed_as_a_ghost(
    core: CacheCore,
    namespace: NamespaceId,
    monkeypatch: pytest.MonkeyPatch,
    begin: Callable[[CacheCore, NamespaceId], object],
    admit: Callable[[CacheCore, object], AdmissionOutcome],
) -> None:
    capture = begin(core, namespace)

    def hook(key: CacheKey, entry: CacheEntry) -> None:
        core._lru.remove_exact(key, entry)

    _patch_conditional_put_hook(monkeypatch, core, hook)

    outcome = admit(core, capture)

    assert outcome is AdmissionOutcome.DECLINED_STALE
    state = core._namespace(namespace)
    assert len(state.entry_index) == 0


@pytest.mark.parametrize(("begin", "admit"), _BEGIN_AND_ADMIT_BY_KIND)
def test_an_entry_evicted_between_the_residency_check_and_publication_is_reclaimed(
    core: CacheCore,
    namespace: NamespaceId,
    monkeypatch: pytest.MonkeyPatch,
    begin: Callable[[CacheCore, NamespaceId], object],
    admit: Callable[[CacheCore, object], AdmissionOutcome],
) -> None:
    capture = begin(core, namespace)

    lru_class = type(core._lru)
    original_contains_exact = lru_class.contains_exact
    triggered = False

    def patched_contains_exact(
        self: WeightedLru, key: CacheKey, entry: CacheEntry
    ) -> bool:
        nonlocal triggered
        result = original_contains_exact(self, key, entry)
        if not triggered and result:
            triggered = True
            # Simulate a concurrent admission's capacity eviction landing
            # exactly between this residency check and publication.
            self.remove_exact(key, entry)
        return result

    monkeypatch.setattr(lru_class, "contains_exact", patched_contains_exact)

    outcome = admit(core, capture)

    assert outcome is AdmissionOutcome.DECLINED_STALE
    state = core._namespace(namespace)
    assert len(state.entry_index) == 0


def test_a_replaced_entry_does_not_leak_its_index_token(
    core: CacheCore, namespace: NamespaceId
) -> None:
    identity = "doc-1"
    read_shape = "full"

    for iteration in range(10):
        capture = core.begin_identity_admission(namespace, identity)
        outcome = core.admit_identity(capture, read_shape, {"v": iteration})
        assert outcome is AdmissionOutcome.ADMITTED
        core.record_write(namespace, identity)

    state = core._namespace(namespace)
    assert len(state.entry_index) == 1


def test_cancelled_admission_is_rejected_at_lookup_but_not_physically_reclaimed(
    core: CacheCore, namespace: NamespaceId
) -> None:
    identity = "doc-1"
    read_shape = "full"
    capture = core.begin_identity_admission(namespace, identity)

    canonical_identity = capture.identity
    canonical_shape = canonicalize(read_shape)
    key = IdentityCacheKey(namespace, canonical_identity, canonical_shape)
    encoded = encode_value({"v": "orphaned"})
    entry = CacheEntry(
        generation_key=capture.generation_key,
        weight=len(encoded),
        value=encoded,
        namespace=namespace,
        identity=canonical_identity,
    )
    admitted, _displaced, _evicted = core._lru.conditional_put(key, entry)
    assert admitted
    core.discard_identity_admission(capture)

    core.record_write(namespace, identity)

    _used_bytes, entry_count = core._lru.snapshot_usage()
    assert entry_count == 1

    result = core.lookup_identity(namespace, identity, read_shape)
    assert result.hit is False


def test_an_orphaned_entry_is_not_revalidated_by_a_later_admission_for_the_identity(
    core: CacheCore, namespace: NamespaceId
) -> None:
    identity = "doc-1"
    orphaned_shape = "orphaned-shape"
    capture = core.begin_identity_admission(namespace, identity)

    canonical_identity = capture.identity
    canonical_shape = canonicalize(orphaned_shape)
    orphaned_key = IdentityCacheKey(namespace, canonical_identity, canonical_shape)
    encoded = encode_value({"v": "orphaned"})
    orphaned_entry = CacheEntry(
        generation_key=capture.generation_key,
        weight=len(encoded),
        value=encoded,
        namespace=namespace,
        identity=canonical_identity,
    )
    admitted, _displaced, _evicted = core._lru.conditional_put(
        orphaned_key, orphaned_entry
    )
    assert admitted
    core.discard_identity_admission(capture)

    state = core._namespace(namespace)
    assert identity not in state.identities

    fresh_capture = core.begin_identity_admission(namespace, identity)
    outcome = core.admit_identity(fresh_capture, "fresh-shape", {"v": "fresh"})
    assert outcome is AdmissionOutcome.ADMITTED

    orphaned_result = core.lookup_identity(namespace, identity, orphaned_shape)
    assert orphaned_result.hit is False


def test_a_pruned_high_generation_identity_does_not_block_future_admissions(
    core: CacheCore, namespace: NamespaceId
) -> None:
    identity = "doc-1"
    read_shape = "shared-shape"
    write_count = 50

    # Keep the identity tracked (via an open capture) while driving its
    # generation up with writes, without ever successfully admitting a
    # resident entry for it.
    holder_capture = core.begin_identity_admission(namespace, identity)
    for _ in range(write_count):
        core.record_write(namespace, identity)

    # Orphan an entry at the identity's now-high generation, under the same
    # key a later, legitimate admission will use, bypassing the normal
    # publish step.
    orphan_capture = core.begin_identity_admission(namespace, identity)
    canonical_identity = orphan_capture.identity
    canonical_shape = canonicalize(read_shape)
    key = IdentityCacheKey(namespace, canonical_identity, canonical_shape)
    encoded = encode_value({"v": "orphan"})
    orphaned_entry = CacheEntry(
        generation_key=orphan_capture.generation_key,
        weight=len(encoded),
        value=encoded,
        namespace=namespace,
        identity=canonical_identity,
    )
    admitted, _displaced, _evicted = core._lru.conditional_put(key, orphaned_entry)
    assert admitted
    core.discard_identity_admission(orphan_capture)
    core.discard_identity_admission(holder_capture)

    state = core._namespace(namespace)
    assert identity not in state.identities

    # A fresh admission under the same key must not be rejected by
    # conditional_put as "older" than the still-resident orphan.
    fresh_capture = core.begin_identity_admission(namespace, identity)
    outcome = core.admit_identity(fresh_capture, read_shape, {"v": "fresh"})
    assert outcome is AdmissionOutcome.ADMITTED

    result = core.lookup_identity(namespace, identity, read_shape)
    assert result.hit
    assert result.value == {"v": "fresh"}


def test_a_namespace_clear_reclaims_a_normally_completed_admission(
    core: CacheCore, namespace: NamespaceId
) -> None:
    capture = core.begin_identity_admission(namespace, "doc-1")
    outcome = core.admit_identity(capture, "full", {"v": 1})
    assert outcome is AdmissionOutcome.ADMITTED

    core.clear_namespace(namespace)

    used_bytes, entry_count = core._lru.snapshot_usage()
    assert used_bytes == 0
    assert entry_count == 0


def test_no_code_path_holds_the_namespace_lock_and_the_lru_lock_at_once(
    core: CacheCore, namespace: NamespaceId
) -> None:
    def worker(worker_id: int) -> None:
        for iteration in range(50):
            identity = f"doc-{worker_id}-{iteration % 5}"
            capture = core.begin_identity_admission(namespace, identity)
            core.admit_identity(capture, "full", {"v": iteration})
            core.lookup_identity(namespace, identity, "full")
            core.record_write(namespace, identity)
            if iteration % 10 == 0:
                core.clear_namespace(namespace)
            namespace_capture = core.capture_namespace_generation(namespace)
            core.admit_namespace(namespace_capture, ("q", iteration), [1, 2, 3])
            core.lookup_namespace(namespace, ("q", iteration))

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, worker_id) for worker_id in range(8)]
        for future in futures:
            future.result()


def test_the_lock_order_guard_would_catch_a_real_nesting_bug(
    core: CacheCore, namespace: NamespaceId
) -> None:
    state = core._namespace(namespace)
    with (
        pytest.raises(LockOrderViolationError),
        core._namespace_section(state),
        core._guard.lru_section(),
    ):
        pass


def test_identity_capture_can_be_discarded_without_admitting(
    core: CacheCore, namespace: NamespaceId
) -> None:
    capture = core.begin_identity_admission(namespace, "doc-1")
    core.discard_identity_admission(capture)

    state = core._namespace(namespace)
    assert "doc-1" not in state.identities


def test_double_discard_of_a_capture_is_a_no_op(
    core: CacheCore, namespace: NamespaceId
) -> None:
    capture = core.begin_identity_admission(namespace, "doc-1")
    core.discard_identity_admission(capture)
    core.discard_identity_admission(capture)


def test_thread_local_guard_is_isolated_per_thread(core: CacheCore) -> None:
    errors: list[BaseException] = []

    def hold_namespace_section() -> None:
        try:
            with core._guard.namespace_section():
                pass
        except BaseException as error:  # noqa: BLE001
            errors.append(error)

    with core._guard.lru_section():
        thread = threading.Thread(target=hold_namespace_section)
        thread.start()
        thread.join()

    assert not errors


def test_a_rolled_back_admission_still_discards_the_entry_it_displaced(
    core: CacheCore, namespace: NamespaceId, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = "doc-1"
    read_shape = "full"

    first_capture = core.begin_identity_admission(namespace, identity)
    outcome = core.admit_identity(first_capture, read_shape, {"v": "first"})
    assert outcome is AdmissionOutcome.ADMITTED

    core.record_write(namespace, identity)
    second_capture = core.begin_identity_admission(namespace, identity)
    triggered = False

    def hook(_key: CacheKey, entry: CacheEntry) -> None:
        nonlocal triggered
        if triggered or entry.generation_key != second_capture.generation_key:
            return
        triggered = True
        core.record_write(namespace, identity)

    _patch_conditional_put_hook(monkeypatch, core, hook)

    outcome = core.admit_identity(second_capture, read_shape, {"v": "second"})
    assert outcome is AdmissionOutcome.DECLINED_STALE

    state = core._namespace(namespace)
    assert len(state.entry_index) == 0
    assert identity not in state.identities
