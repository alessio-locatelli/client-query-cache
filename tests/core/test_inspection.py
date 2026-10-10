from __future__ import annotations

import dataclasses
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import pytest

from client_query_cache import BypassReason, BypassReasonCount
from client_query_cache._core.canonical import canonicalize
from client_query_cache._core.codec import encode_value
from client_query_cache._core.entries import AdmissionOutcome, CacheEntry
from client_query_cache._core.keys import NamespaceCacheKey
from client_query_cache._core.manager import CacheCore, CacheCoreConfig
from client_query_cache._types import BsonDict

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from client_query_cache._core.keys import NamespaceId

pytestmark = pytest.mark.unit


def test_snapshot_is_immutable(core: CacheCore) -> None:
    snapshot = core.snapshot()
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.hits = 99  # type: ignore[misc]


def test_snapshot_only_exposes_safe_primitive_fields(core: CacheCore) -> None:
    snapshot = core.snapshot()
    for field in dataclasses.fields(snapshot):
        value = getattr(snapshot, field.name)
        if field.name == "bypass_reasons":
            assert isinstance(value, tuple)
            assert all(isinstance(record, BypassReasonCount) for record in value)
        else:
            assert isinstance(value, (str, int))


def test_snapshot_reports_capacity_and_lifecycle(core: CacheCore) -> None:
    snapshot = core.snapshot()
    assert snapshot.lifecycle == "active"
    assert snapshot.shared_budget_bytes > 0
    assert snapshot.max_entry_bytes > 0
    assert snapshot.used_bytes == 0
    assert snapshot.entry_count == 0


def test_snapshot_tracks_hits_and_misses(
    core: CacheCore, namespace: NamespaceId
) -> None:
    core.lookup_identity(namespace, "doc-1", "full")
    capture = core.begin_identity_admission(namespace, "doc-1")
    outcome = core.admit_identity(capture, "full", {"v": 1})
    assert outcome is AdmissionOutcome.ADMITTED
    core.lookup_identity(namespace, "doc-1", "full")

    snapshot = core.snapshot()
    assert snapshot.misses == 1
    assert snapshot.hits == 1


_DISCRIMINATOR: tuple[str, BsonDict] = ("find", {})


def _seed_valid_entry(core: CacheCore, namespace: NamespaceId) -> None:
    capture = core.capture_namespace_generation(namespace)
    core.admit_namespace(capture, _DISCRIMINATOR, ["current"])


def _seed_stale_entry(core: CacheCore, namespace: NamespaceId) -> None:
    capture = core.capture_namespace_generation(namespace)
    encoded = encode_value(["stale"])
    entry = CacheEntry(
        generation_key=(capture.generation,),
        weight=len(encoded),
        value=encoded,
        namespace=namespace,
        identity=None,
    )
    key = NamespaceCacheKey(namespace, canonicalize(_DISCRIMINATOR))
    admitted, _displaced, _evicted = core._lru.conditional_put(key, entry)
    assert admitted
    core.clear_namespace(namespace)


@pytest.mark.parametrize("defer_miss", [False, True])
@pytest.mark.parametrize(
    ("seed", "hit"),
    [
        pytest.param(lambda _core, _namespace: None, False, id="absent"),
        pytest.param(_seed_stale_entry, False, id="stale"),
        pytest.param(_seed_valid_entry, True, id="valid"),
    ],
)
def test_namespace_lookup_defers_only_a_requested_miss(
    core: CacheCore,
    namespace: NamespaceId,
    seed: Callable[[CacheCore, NamespaceId], None],
    *,
    hit: bool,
    defer_miss: bool,
) -> None:
    seed(core, namespace)

    lookup_result = core.lookup_namespace(
        namespace, _DISCRIMINATOR, defer_miss=defer_miss
    )

    snapshot = core.snapshot()
    assert lookup_result.hit is hit
    assert lookup_result.deferred_miss is (defer_miss and not hit)
    assert snapshot.hits == int(hit)
    assert snapshot.misses == int(not hit and not defer_miss)
    assert snapshot.bypasses == 0


def test_a_deferred_miss_is_recorded_once_on_request(
    core: CacheCore, namespace: NamespaceId
) -> None:
    core.lookup_namespace(namespace, _DISCRIMINATOR, defer_miss=True)

    core.record_miss()

    assert core.snapshot().misses == 1


def test_an_unavailable_database_records_a_bypass_instead_of_deferring_a_miss(
    core: CacheCore, namespace: NamespaceId
) -> None:
    core.set_database_available(namespace.database, available=False)

    lookup_result = core.lookup_namespace(namespace, _DISCRIMINATOR, defer_miss=True)

    snapshot = core.snapshot()
    assert lookup_result.deferred_miss is False
    assert snapshot.misses == 0
    assert snapshot.bypasses == 1


def test_snapshot_tracks_evictions(namespace: NamespaceId) -> None:
    core = CacheCore(CacheCoreConfig(shared_budget_bytes=100, max_entry_bytes=50))
    for index in range(20):
        capture = core.begin_identity_admission(namespace, f"doc-{index}")
        core.admit_identity(capture, "full", {"v": "x" * 20})

    assert core.snapshot().evictions > 0


@pytest.mark.parametrize(
    "reason",
    [None, *BypassReason],
    ids=("default", *(reason.value for reason in BypassReason)),
)
def test_snapshot_tracks_bypasses(core: CacheCore, reason: BypassReason | None) -> None:
    bypass_count = 2
    for _ in range(bypass_count):
        if reason is None:
            core.record_bypass()
        else:
            core.record_bypass(reason)

    snapshot = core.snapshot()
    assert snapshot.bypasses == bypass_count
    assert tuple(record.reason for record in snapshot.bypass_reasons) == tuple(
        BypassReason
    )
    assert sum(record.count for record in snapshot.bypass_reasons) == bypass_count
    recorded_reason = reason if reason is not None else BypassReason.UNSPECIFIED
    assert (
        next(
            record.count
            for record in snapshot.bypass_reasons
            if record.reason is recorded_reason
        )
        == bypass_count
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.bypass_reasons[0].count = 99  # type: ignore[misc]


def test_logs_never_include_document_query_credential_or_resume_token_content(
    core: CacheCore, namespace: NamespaceId, caplog: pytest.LogCaptureFixture
) -> None:
    sensitive_markers = (
        "sensitive-account-secret",  # pragma: allowlist secret
        "resume-token-abc123",
        "credential-xyz",
    )
    with caplog.at_level("DEBUG", logger="client_query_cache._core.manager"):
        capture = core.begin_identity_admission(
            namespace, {"credential": "credential-xyz"}
        )
        core.admit_identity(
            capture,
            {"query": "resume-token-abc123"},
            {"secret_field": "sensitive-account-secret"},  # pragma: allowlist secret
        )
        core.clear_namespace(namespace)
        core.close()

    assert caplog.records
    for record in caplog.records:
        rendered = record.getMessage() + str(getattr(record, "__dict__", {}))
        for marker in sensitive_markers:
            assert marker not in rendered


@pytest.fixture
def concurrent_recordings(core: CacheCore) -> Generator[None]:
    started = threading.Event()
    finish = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(record_until_finished, core, started, finish)
        assert started.wait(5)
        yield
        finish.set()
        future.result(timeout=5)


def record_until_finished(
    core: CacheCore, started: threading.Event, finish: threading.Event
) -> None:
    core.record_bypass(BypassReason.SESSION)
    started.set()
    while not finish.is_set():
        core.record_bypass(BypassReason.STREAM_UNAVAILABLE)


@pytest.mark.usefixtures("concurrent_recordings")
def test_concurrent_snapshot_reason_totals(core: CacheCore) -> None:
    for _ in range(100):
        snapshot = core.snapshot()
        assert (
            sum(record.count for record in snapshot.bypass_reasons) == snapshot.bypasses
        )


def test_oversized_admission_does_not_record_an_ordinary_reason(
    core: CacheCore, namespace: NamespaceId
) -> None:
    before = core.snapshot()
    capture = core.capture_namespace_generation(namespace)
    assert (
        core.admit_namespace(capture, "oversized", "x" * before.max_entry_bytes)
        is AdmissionOutcome.DECLINED_OVERSIZE
    )
    after = core.snapshot()
    assert after.oversized_bypasses == before.oversized_bypasses + 1
    assert after.bypasses == before.bypasses
    assert after.bypass_reasons == before.bypass_reasons
