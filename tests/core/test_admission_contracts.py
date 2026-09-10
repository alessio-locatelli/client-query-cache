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

if TYPE_CHECKING:
    from mongo_client_cache._core.keys import CacheKey
    from mongo_client_cache._core.lru import WeightedLru

pytestmark = pytest.mark.unit


def test_identity_admission_rejects_an_unsupported_identity(
    core: CacheCore, namespace: NamespaceId
) -> None:
    with pytest.raises(UnsupportedCacheRequestError):
        core.begin_identity_admission(namespace, {1, 2, 3})


def test_identity_admission_rejects_an_unsupported_read_shape(
    core: CacheCore, namespace: NamespaceId
) -> None:
    capture = core.begin_identity_admission(namespace, "doc-1")
    with pytest.raises(UnsupportedCacheRequestError):
        core.admit_identity(capture, {1, 2, 3}, {"a": 1})


def test_namespace_admission_rejects_an_unsupported_discriminator(
    core: CacheCore, namespace: NamespaceId
) -> None:
    capture = core.capture_namespace_generation(namespace)
    with pytest.raises(UnsupportedCacheRequestError):
        core.admit_namespace(capture, {1, 2, 3}, [])


def test_admission_rejects_an_oversize_value(namespace: NamespaceId) -> None:
    core = CacheCore(CacheCoreConfig(shared_budget_bytes=1_000, max_entry_bytes=32))
    capture = core.begin_identity_admission(namespace, "doc-1")
    outcome = core.admit_identity(capture, "full", {"payload": "x" * 100})
    assert outcome is AdmissionOutcome.DECLINED_OVERSIZE


def test_a_rollback_does_not_delete_a_newer_replacement(
    core: CacheCore, namespace: NamespaceId, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = "doc-1"
    read_shape = "full"
    capture_stale = core.begin_identity_admission(namespace, identity)

    lru_class = type(core._lru)
    original_conditional_put = lru_class.conditional_put
    triggered = False

    def racing_conditional_put(
        self: WeightedLru, key: CacheKey, entry: CacheEntry
    ) -> object:
        nonlocal triggered
        result = original_conditional_put(self, key, entry)
        if not triggered and entry.generation_key == capture_stale.generation_key:
            triggered = True
            core.record_write(namespace, identity)
            fresh_capture = core.begin_identity_admission(namespace, identity)
            outcome = core.admit_identity(fresh_capture, read_shape, {"v": "fresh"})
            assert outcome is AdmissionOutcome.ADMITTED
        return result

    monkeypatch.setattr(lru_class, "conditional_put", racing_conditional_put)

    outcome = core.admit_identity(capture_stale, read_shape, {"v": "stale"})

    assert outcome is AdmissionOutcome.DECLINED_STALE
    result = core.lookup_identity(namespace, identity, read_shape)
    assert result.hit
    assert result.value == {"v": "fresh"}


def test_a_late_stale_insertion_cannot_clobber_a_fresher_entry(
    core: CacheCore, namespace: NamespaceId, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = "doc-1"
    read_shape = "full"
    capture_stale = core.begin_identity_admission(namespace, identity)

    lru_class = type(core._lru)
    original_conditional_put = lru_class.conditional_put
    triggered = False

    def racing_conditional_put(
        self: WeightedLru, key: CacheKey, entry: CacheEntry
    ) -> object:
        nonlocal triggered
        if not triggered and entry.generation_key == capture_stale.generation_key:
            triggered = True
            core.record_write(namespace, identity)
            fresh_capture = core.begin_identity_admission(namespace, identity)
            outcome = core.admit_identity(fresh_capture, read_shape, {"v": "fresh"})
            assert outcome is AdmissionOutcome.ADMITTED
        return original_conditional_put(self, key, entry)

    monkeypatch.setattr(lru_class, "conditional_put", racing_conditional_put)

    outcome = core.admit_identity(capture_stale, read_shape, {"v": "stale"})

    assert outcome is AdmissionOutcome.DECLINED_STALE
    result = core.lookup_identity(namespace, identity, read_shape)
    assert result.hit
    assert result.value == {"v": "fresh"}


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
