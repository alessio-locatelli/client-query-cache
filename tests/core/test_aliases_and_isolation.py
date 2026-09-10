from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mongo_client_cache._core.entries import AdmissionOutcome
from mongo_client_cache._core.keys import canonical_alias_key
from mongo_client_cache._core.manager import CacheCore, CacheCoreConfig

if TYPE_CHECKING:
    from mongo_client_cache._core.entries import CacheEntry
    from mongo_client_cache._core.keys import CacheKey, NamespaceId
    from mongo_client_cache._core.lru import WeightedLru

pytestmark = pytest.mark.unit


def test_caller_mutation_does_not_affect_a_later_hit(
    core: CacheCore, namespace: NamespaceId
) -> None:
    identity = "doc-1"
    capture = core.begin_identity_admission(namespace, identity)
    original = {"a": [1, 2, 3]}
    core.admit_identity(capture, "full", original)
    original["a"].append(4)

    result = core.lookup_identity(namespace, identity, "full")
    assert result.value == {"a": [1, 2, 3]}

    assert isinstance(result.value, dict)
    result.value["a"].append(999)
    second_result = core.lookup_identity(namespace, identity, "full")
    assert second_result.value == {"a": [1, 2, 3]}


def test_clearing_discards_aliases_and_budget_for_a_racing_rolled_back_admission(
    core: CacheCore, namespace: NamespaceId, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = core.begin_identity_admission(namespace, "doc-1")
    alias = canonical_alias_key("email", "a@example.com", None)

    lru_class = type(core._lru)
    original_conditional_put = lru_class.conditional_put
    triggered = False

    def racing_conditional_put(
        self: WeightedLru, key: CacheKey, entry: CacheEntry
    ) -> object:
        nonlocal triggered
        result = original_conditional_put(self, key, entry)
        if not triggered and entry.generation_key == capture.generation_key:
            triggered = True
            core.clear_namespace(namespace)
        return result

    monkeypatch.setattr(lru_class, "conditional_put", racing_conditional_put)

    outcome = core.admit_identity(capture, "full", {"v": 1}, alias=alias)

    assert outcome is AdmissionOutcome.DECLINED_STALE
    used_bytes, entry_count = core._lru.snapshot_usage()
    assert used_bytes == 0
    assert entry_count == 0
    assert core.resolve_alias(namespace, "email", "a@example.com", None) is None


def test_a_stale_pre_clear_alias_cannot_reach_a_post_clear_entry(
    core: CacheCore, namespace: NamespaceId
) -> None:
    old_identity = "doc-old"
    old_capture = core.begin_identity_admission(namespace, old_identity)
    alias = canonical_alias_key("email", "shared@example.com", None)
    core.admit_identity(old_capture, "full", {"v": "old"}, alias=alias)

    core.clear_namespace(namespace)

    new_identity = "doc-new"
    new_capture = core.begin_identity_admission(namespace, new_identity)
    core.admit_identity(new_capture, "full", {"v": "new"})

    assert core.resolve_alias(namespace, "email", "shared@example.com", None) is None


def test_different_unique_keys_sharing_a_value_do_not_collide(
    core: CacheCore, namespace: NamespaceId
) -> None:
    capture_a = core.begin_identity_admission(namespace, "doc-a")
    alias_email = canonical_alias_key("email", "shared-value", None)
    core.admit_identity(capture_a, "full", {"v": "a"}, alias=alias_email)

    capture_b = core.begin_identity_admission(namespace, "doc-b")
    alias_username = canonical_alias_key("username", "shared-value", None)
    core.admit_identity(capture_b, "full", {"v": "b"}, alias=alias_username)

    assert core.resolve_alias(namespace, "email", "shared-value", None) == "doc-a"
    assert core.resolve_alias(namespace, "username", "shared-value", None) == "doc-b"


def test_a_resolution_under_one_collation_is_not_reused_for_another(
    core: CacheCore, namespace: NamespaceId
) -> None:
    capture = core.begin_identity_admission(namespace, "doc-ci")
    alias_case_insensitive = canonical_alias_key("email", "value", "case-insensitive")
    core.admit_identity(capture, "full", {"v": "ci"}, alias=alias_case_insensitive)

    assert core.resolve_alias(namespace, "email", "value", "simple") is None
    resolved = core.resolve_alias(namespace, "email", "value", "case-insensitive")
    assert resolved == "doc-ci"


def test_a_resolution_racing_a_concurrent_write_is_not_published(
    core: CacheCore, namespace: NamespaceId
) -> None:
    identity = "doc-1"
    capture = core.begin_identity_admission(namespace, identity)
    core.record_write(namespace, identity)

    alias = canonical_alias_key("email", "a@example.com", None)
    outcome = core.admit_identity(capture, "full", {"v": 1}, alias=alias)

    assert outcome is AdmissionOutcome.DECLINED_STALE
    assert core.resolve_alias(namespace, "email", "a@example.com", None) is None


def test_aliases_do_not_grow_unboundedly_under_sustained_distinct_key_reads(
    namespace: NamespaceId,
) -> None:
    core = CacheCore(CacheCoreConfig(shared_budget_bytes=500, max_entry_bytes=100))
    admission_count = 500

    for index in range(admission_count):
        capture = core.begin_identity_admission(namespace, f"doc-{index}")
        alias = canonical_alias_key("key", f"value-{index}", None)
        core.admit_identity(capture, "full", {"v": index}, alias=alias)

    state = core._namespace(namespace)
    assert len(state.aliases) < admission_count


def test_an_inflight_read_racing_a_clear_is_rejected_rather_than_repopulating(
    core: CacheCore, namespace: NamespaceId
) -> None:
    identity = "doc-1"
    capture = core.begin_identity_admission(namespace, identity)

    core.clear_namespace(namespace)

    outcome = core.admit_identity(capture, "full", {"v": "stale-value"})

    assert outcome is AdmissionOutcome.DECLINED_STALE
    assert core.lookup_identity(namespace, identity, "full").hit is False
