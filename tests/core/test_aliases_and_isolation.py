from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mongo_client_cache._core.entries import AdmissionOutcome
from mongo_client_cache._core.keys import canonical_alias_key
from mongo_client_cache._core.manager import CacheCore, CacheCoreConfig
from tests.core.conftest import patch_conditional_put_hook

if TYPE_CHECKING:
    from mongo_client_cache._core.entries import CacheEntry
    from mongo_client_cache._core.keys import CacheKey, NamespaceId

pytestmark = pytest.mark.unit


def test_caller_mutation_does_not_affect_a_later_hit(
    core: CacheCore, namespace: NamespaceId
) -> None:
    identity = "doc-1"
    capture = core.begin_identity_admission(namespace, identity)
    original = {"a": [1, 2, 3]}
    core.admit_identity(capture, "full", original)
    original["a"].append(4)

    lookup_result = core.lookup_identity(namespace, identity, "full")
    assert lookup_result.value == {"a": [1, 2, 3]}

    assert isinstance(lookup_result.value, dict)
    lookup_result.value["a"].append(999)
    second_result = core.lookup_identity(namespace, identity, "full")
    assert second_result.value == {"a": [1, 2, 3]}


def test_clearing_discards_aliases_and_budget_for_a_racing_rolled_back_admission(
    core: CacheCore, namespace: NamespaceId, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = core.begin_identity_admission(namespace, "doc-1")
    alias = canonical_alias_key("email", "a@example.com", None)

    # admit_identity() calls conditional_put() exactly once per attempt, and
    # this test only ever admits `capture`, so the hook itself never needs
    # to guard against being re-triggered.
    def hook(_key: CacheKey, _entry: CacheEntry) -> None:
        core.clear_namespace(namespace)

    patch_conditional_put_hook(monkeypatch, core, hook)

    outcome = core.admit_identity(capture, "full", {"v": 1}, alias=alias)

    assert outcome is AdmissionOutcome.DECLINED_STALE
    used_bytes, entry_count = core._lru.snapshot_usage()
    assert used_bytes == 0
    assert entry_count == 0
    assert core.resolve_alias(namespace, "email", "a@example.com", None) is None


def test_a_stale_pre_clear_alias_cannot_reach_a_post_clear_entry(
    core: CacheCore, namespace: NamespaceId
) -> None:
    old_capture = core.begin_identity_admission(namespace, "doc-old")
    alias = canonical_alias_key("email", "shared@example.com", None)
    core.admit_identity(old_capture, "full", {"v": "old"}, alias=alias)

    core.clear_namespace(namespace)

    new_capture = core.begin_identity_admission(namespace, "doc-new")
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


def test_lookup_by_alias_returns_the_cached_value_for_a_valid_resolution(
    core: CacheCore, namespace: NamespaceId
) -> None:
    capture = core.begin_identity_admission(namespace, "doc-1")
    alias = canonical_alias_key("email", "a@example.com", None)
    core.admit_identity(capture, "full", {"v": "current"}, alias=alias)

    lookup_result = core.lookup_by_alias(
        namespace, "email", "a@example.com", None, "full"
    )

    assert lookup_result.hit
    assert lookup_result.value == {"v": "current"}


def test_lookup_by_alias_misses_when_no_alias_is_resolved(
    core: CacheCore, namespace: NamespaceId
) -> None:
    lookup_result = core.lookup_by_alias(
        namespace, "email", "missing@example.com", None, "full"
    )
    assert lookup_result.hit is False


def test_lookup_by_alias_does_not_return_a_document_the_alias_no_longer_matches(
    core: CacheCore, namespace: NamespaceId
) -> None:
    identity = "doc-1"
    capture = core.begin_identity_admission(namespace, identity)
    alias = canonical_alias_key("email", "a@example.com", None)
    core.admit_identity(capture, "full", {"v": "old-email-value"}, alias=alias)

    # The document's email changes; a write drops the stale alias immediately,
    # then a fresh identity-guarded entry is cached for the same document.
    core.record_write(namespace, identity)
    fresh_capture = core.begin_identity_admission(namespace, identity)
    core.admit_identity(fresh_capture, "full", {"v": "new-email-value"})

    lookup_result = core.lookup_by_alias(
        namespace, "email", "a@example.com", None, "full"
    )

    assert lookup_result.hit is False


def test_a_write_racing_between_resolve_alias_and_lookup_identity_is_not_masked(
    core: CacheCore, namespace: NamespaceId
) -> None:
    identity = "doc-1"
    capture = core.begin_identity_admission(namespace, identity)
    alias = canonical_alias_key("email", "a@example.com", None)
    core.admit_identity(capture, "full", {"v": "old-email-value"}, alias=alias)

    resolved_identity = core.resolve_alias(namespace, "email", "a@example.com", None)
    assert resolved_identity == identity

    core.record_write(namespace, identity)
    fresh_capture = core.begin_identity_admission(namespace, identity)
    core.admit_identity(fresh_capture, "full", {"v": "new-email-value"})

    # A caller composing resolve_alias() with a bare lookup_identity() would
    # incorrectly see the document's *current* contents as if they still
    # matched the old email; lookup_by_alias re-validates the alias itself
    # and correctly misses instead.
    stale_composition = core.lookup_identity(namespace, resolved_identity, "full")
    assert stale_composition.hit

    lookup_result = core.lookup_by_alias(
        namespace, "email", "a@example.com", None, "full"
    )
    assert lookup_result.hit is False


def test_repointing_an_alias_to_a_new_identity_survives_the_old_owners_cleanup(
    core: CacheCore, namespace: NamespaceId
) -> None:
    alias = canonical_alias_key("email", "shared@example.com", None)

    old_owner = "doc-old"
    old_capture = core.begin_identity_admission(namespace, old_owner)
    core.admit_identity(old_capture, "full", {"v": "old-owner"}, alias=alias)

    new_owner = "doc-new"
    new_capture = core.begin_identity_admission(namespace, new_owner)
    core.admit_identity(new_capture, "full", {"v": "new-owner"}, alias=alias)

    assert core.resolve_alias(namespace, "email", "shared@example.com", None) == (
        new_owner
    )

    # Writing to the old owner must not clean up an alias it no longer owns.
    core.record_write(namespace, old_owner)

    assert core.resolve_alias(namespace, "email", "shared@example.com", None) == (
        new_owner
    )


def test_a_mapping_identity_resolved_via_alias_still_matches_lookup_identity(
    core: CacheCore, namespace: NamespaceId
) -> None:
    identity = {"tenant": "t1", "id": 42}
    capture = core.begin_identity_admission(namespace, identity)
    alias = canonical_alias_key("email", "a@example.com", None)
    core.admit_identity(capture, "full", {"v": "value"}, alias=alias)

    resolved_identity = core.resolve_alias(namespace, "email", "a@example.com", None)
    assert resolved_identity is not None

    lookup_result = core.lookup_identity(namespace, resolved_identity, "full")
    assert lookup_result.hit
    assert lookup_result.value == {"v": "value"}


def test_lookup_by_alias_misses_when_the_resolved_identity_has_no_matching_shape(
    core: CacheCore, namespace: NamespaceId
) -> None:
    capture = core.begin_identity_admission(namespace, "doc-1")
    alias = canonical_alias_key("email", "a@example.com", None)
    core.admit_identity(capture, "full", {"v": "x"}, alias=alias)

    lookup_result = core.lookup_by_alias(
        namespace, "email", "a@example.com", None, "different-shape"
    )

    assert lookup_result.hit is False


def test_lookup_by_alias_misses_a_stale_entry_under_a_still_current_alias(
    core: CacheCore, namespace: NamespaceId
) -> None:
    identity = "doc-1"
    read_shape = "full"
    alias = canonical_alias_key("email", "a@example.com", None)

    capture = core.begin_identity_admission(namespace, identity)
    core.admit_identity(capture, read_shape, {"v": "old"}, alias=alias)

    # The write drops the alias; republishing it for a different read shape
    # leaves the *original* shape's entry stale under an alias that is
    # otherwise still current for the identity.
    core.record_write(namespace, identity)
    fresh_capture = core.begin_identity_admission(namespace, identity)
    core.admit_identity(fresh_capture, "other-shape", {"v": "new"}, alias=alias)

    lookup_result = core.lookup_by_alias(
        namespace, "email", "a@example.com", None, read_shape
    )

    assert lookup_result.hit is False
