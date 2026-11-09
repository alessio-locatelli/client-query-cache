from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from client_query_cache import CacheCore, CacheCoreConfig
from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.keys import canonical_alias_key

if TYPE_CHECKING:
    from collections.abc import Callable

    from client_query_cache._core.keys import AliasKey, NamespaceId

SHARED_ALIAS = canonical_alias_key("email", "shared@example.com", None)

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
    core = CacheCore(CacheCoreConfig(budget_bytes=500, max_entry_bytes=100))
    admission_count = 500

    for index in range(admission_count):
        capture = core.begin_identity_admission(namespace, f"doc-{index}")
        alias = canonical_alias_key("key", f"value-{index}", None)
        core.admit_identity(capture, "full", {"v": index}, alias=alias)

    assert core.resolve_alias(namespace, "key", "value-0", None) is None
    last = admission_count - 1
    assert core.resolve_alias(namespace, "key", f"value-{last}", None) == f"doc-{last}"


@pytest.mark.parametrize(
    "alias",
    [None, canonical_alias_key("email", "a@example.com", None)],
    ids=["without-alias", "with-alias"],
)
@pytest.mark.parametrize("core", [True], indirect=True, ids=["telemetry"])
def test_an_inflight_read_racing_a_clear_is_rejected_rather_than_repopulating(
    core: CacheCore, namespace: NamespaceId, alias: AliasKey | None
) -> None:
    identity = "doc-1"
    capture = core.begin_identity_admission(namespace, identity)

    core.clear_namespace(namespace)

    outcome = core.admit_identity(capture, "full", {"v": "stale-value"}, alias=alias)

    assert outcome is AdmissionOutcome.DECLINED_STALE
    assert core.lookup_identity(namespace, identity, "full").hit is False
    assert core.resolve_alias(namespace, "email", "a@example.com", None) is None
    snapshot = core.snapshot()
    assert snapshot.used_bytes == 0
    assert snapshot.entry_count == 0


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


def _repoint_shared_alias(core: CacheCore, namespace: NamespaceId) -> None:
    core.admit_identity(
        core.begin_identity_admission(namespace, "doc-new"),
        "full",
        {"v": "new"},
        alias=SHARED_ALIAS,
    )


def _write_old_owner(core: CacheCore, namespace: NamespaceId) -> None:
    core.record_write(namespace, "doc-old")


@pytest.mark.parametrize(
    ("release", "current_owner"),
    [
        pytest.param(_repoint_shared_alias, "doc-new", id="repointed"),
        pytest.param(_write_old_owner, None, id="written"),
        pytest.param(CacheCore.clear_namespace, None, id="cleared"),
    ],
)
def test_a_shared_alias_resolves_to_its_current_owner_after_the_old_owner_leaves(
    core: CacheCore,
    namespace: NamespaceId,
    release: Callable[[CacheCore, NamespaceId], None],
    current_owner: str | None,
) -> None:
    core.admit_identity(
        core.begin_identity_admission(namespace, "doc-old"),
        "full",
        {"v": "old"},
        alias=SHARED_ALIAS,
    )
    pending = core.begin_identity_admission(namespace, "doc-old")

    release(core, namespace)

    resolved = core.resolve_alias(namespace, "email", "shared@example.com", None)
    assert resolved == current_owner
    pending.release()
    assert core.resolve_alias(namespace, "email", "shared@example.com", None) == (
        current_owner
    )
