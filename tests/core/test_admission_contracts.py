from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import pytest

from client_query_cache import CacheCore, CacheCoreConfig
from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.errors import UnsupportedCacheRequestError

if TYPE_CHECKING:
    from collections.abc import Callable

    from client_query_cache._core.entries import LookupResult
    from client_query_cache._core.keys import NamespaceId
    from client_query_cache._types import NonNegativeInt

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
    core = CacheCore(CacheCoreConfig(budget_bytes=1_000, max_entry_bytes=32))
    capture = core.begin_identity_admission(namespace, "doc-1")
    outcome = core.admit_identity(capture, "full", {"payload": "x" * 100})
    assert outcome is AdmissionOutcome.DECLINED_OVERSIZE


def test_an_identity_written_while_captured_admits_normally_after_release(
    core: CacheCore, namespace: NamespaceId
) -> None:
    identity = "doc-1"
    read_shape = "shared-shape"
    write_count = 50

    holder_capture = core.begin_identity_admission(namespace, identity)
    for _ in range(write_count):
        core.record_write(namespace, identity)
    holder_capture.release()

    fresh_capture = core.begin_identity_admission(namespace, identity)
    outcome = core.admit_identity(fresh_capture, read_shape, {"v": "fresh"})
    assert outcome is AdmissionOutcome.ADMITTED

    lookup_result = core.lookup_identity(namespace, identity, read_shape)
    assert lookup_result.hit
    assert lookup_result.value == {"v": "fresh"}


@pytest.mark.parametrize(
    ("begin", "admit", "lookup"),
    [
        pytest.param(
            lambda core, namespace: core.begin_identity_admission(namespace, "doc-1"),
            lambda core, capture, value: core.admit_identity(capture, "full", value),
            lambda core, namespace: core.lookup_identity(namespace, "doc-1", "full"),
            id="identity_guarded",
        ),
        pytest.param(
            lambda core, namespace: core.capture_namespace_generation(namespace),
            lambda core, capture, value: core.admit_namespace(
                capture, ("find", {}), value
            ),
            lambda core, namespace: core.lookup_namespace(namespace, ("find", {})),
            id="namespace_guarded",
        ),
    ],
)
def test_a_stale_capture_cannot_displace_a_fresher_admission(
    core: CacheCore,
    namespace: NamespaceId,
    begin: Callable[[CacheCore, NamespaceId], object],
    admit: Callable[[CacheCore, object, object], AdmissionOutcome],
    lookup: Callable[[CacheCore, NamespaceId], LookupResult],
) -> None:
    stale_capture = begin(core, namespace)  # pytriage: TR5 (captured before the write)
    core.record_write(namespace, "doc-1")
    assert admit(core, begin(core, namespace), ["fresh"]) is AdmissionOutcome.ADMITTED

    assert admit(core, stale_capture, ["stale"]) is AdmissionOutcome.DECLINED_STALE

    assert lookup(core, namespace).value == ["fresh"]


@pytest.mark.parametrize("core", [True], indirect=True, ids=["telemetry"])
def test_a_namespace_clear_reclaims_a_normally_completed_admission(
    core: CacheCore, namespace: NamespaceId
) -> None:
    capture = core.begin_identity_admission(namespace, "doc-1")
    outcome = core.admit_identity(capture, "full", {"v": 1})
    assert outcome is AdmissionOutcome.ADMITTED

    core.clear_namespace(namespace)

    snapshot = core.snapshot()
    assert snapshot.used_bytes == 0
    assert snapshot.entry_count == 0


def test_concurrent_admissions_lookups_and_invalidations_complete(
    core: CacheCore, namespace: NamespaceId
) -> None:
    # Eight workers repeat 50 operations each; five IDs per worker force reuse,
    # and clearing every tenth iteration interleaves namespace invalidation.
    def worker(worker_id: NonNegativeInt) -> None:
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


@pytest.mark.parametrize("core", [True], indirect=True, ids=["telemetry"])
def test_identity_capture_can_be_discarded_without_admitting(
    core: CacheCore, namespace: NamespaceId
) -> None:
    capture = core.begin_identity_admission(namespace, "doc-1")
    capture.release()

    assert core.snapshot().entry_count == 0


def test_double_discard_of_a_capture_is_a_no_op(
    core: CacheCore, namespace: NamespaceId
) -> None:
    capture = core.begin_identity_admission(namespace, "doc-1")
    capture.release()
    capture.release()


class _Unencodable:
    __slots__ = ()


@pytest.mark.parametrize(
    "unencodable_value",
    [
        pytest.param(_Unencodable(), id="unencodable_type"),
        pytest.param(10**20, id="out_of_range_int_overflow"),
    ],
)
def test_admit_identity_declines_when_the_value_cannot_be_encoded(
    core: CacheCore, namespace: NamespaceId, unencodable_value: object
) -> None:
    capture = core.begin_identity_admission(namespace, "doc-1")

    outcome = core.admit_identity(capture, "full", unencodable_value)

    assert outcome is AdmissionOutcome.DECLINED_UNENCODABLE
    assert core.lookup_identity(namespace, "doc-1", "full").hit is False


@pytest.mark.parametrize(
    "unencodable_value",
    [
        pytest.param(_Unencodable(), id="unencodable_type"),
        pytest.param(10**20, id="out_of_range_int_overflow"),
    ],
)
def test_admit_namespace_declines_when_the_value_cannot_be_encoded(
    core: CacheCore, namespace: NamespaceId, unencodable_value: object
) -> None:
    capture = core.capture_namespace_generation(namespace)

    outcome = core.admit_namespace(capture, "shape", unencodable_value)

    assert outcome is AdmissionOutcome.DECLINED_UNENCODABLE
    assert core.lookup_namespace(namespace, "shape").hit is False


def test_a_write_with_an_uncanonicalizable_identity_advances_the_namespace_generation(
    core: CacheCore, namespace: NamespaceId
) -> None:
    capture = core.capture_namespace_generation(namespace)

    core.record_write(namespace, {1, 2, 3})

    outcome = core.admit_namespace(capture, "shape", ["stale"])
    assert outcome is AdmissionOutcome.DECLINED_STALE


def test_record_write_invalidates_an_entry_admitted_under_a_mapping_identity(
    core: CacheCore, namespace: NamespaceId
) -> None:
    identity = {"a": 1, "b": 2}
    capture = core.begin_identity_admission(namespace, identity)
    core.admit_identity(capture, "full", {"v": 1})
    assert core.lookup_identity(namespace, identity, "full").hit is True

    core.record_write(namespace, identity)

    assert core.lookup_identity(namespace, identity, "full").hit is False
