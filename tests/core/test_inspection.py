from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

import pytest

from mongo_client_cache._core.entries import AdmissionOutcome
from mongo_client_cache._core.manager import CacheCore, CacheCoreConfig

if TYPE_CHECKING:
    from mongo_client_cache._core.keys import NamespaceId

pytestmark = pytest.mark.unit


def test_snapshot_is_immutable(core: CacheCore) -> None:
    snapshot = core.snapshot()
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.hits = 99  # type: ignore[misc]


def test_snapshot_only_exposes_safe_primitive_fields(core: CacheCore) -> None:
    snapshot = core.snapshot()
    for field in dataclasses.fields(snapshot):
        value = getattr(snapshot, field.name)
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


def test_snapshot_tracks_evictions(namespace: NamespaceId) -> None:
    core = CacheCore(CacheCoreConfig(shared_budget_bytes=100, max_entry_bytes=50))
    for index in range(20):
        capture = core.begin_identity_admission(namespace, f"doc-{index}")
        core.admit_identity(capture, "full", {"v": "x" * 20})

    assert core.snapshot().evictions > 0


def test_snapshot_tracks_bypasses(core: CacheCore) -> None:
    bypass_count = 2
    for _ in range(bypass_count):
        core.record_bypass()

    assert core.snapshot().bypasses == bypass_count


def test_logs_never_include_document_query_credential_or_resume_token_content(
    core: CacheCore, namespace: NamespaceId, caplog: pytest.LogCaptureFixture
) -> None:
    sensitive_markers = (
        "sensitive-account-secret",  # pragma: allowlist secret
        "resume-token-abc123",
        "credential-xyz",
    )
    with caplog.at_level("DEBUG", logger="mongo_client_cache._core.manager"):
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
