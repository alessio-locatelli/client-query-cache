from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from client_query_cache import CacheCore, CacheCoreConfig
from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.errors import UnsupportedCacheRequestError
from client_query_cache._core.keys import canonical_alias_key

if TYPE_CHECKING:
    from collections.abc import Callable

    from client_query_cache._core.keys import NamespaceId

pytestmark = pytest.mark.unit


class _Unencodable:
    __slots__ = ()


def test_a_first_time_match_admits_both_a_namespace_and_identity_guarded_entry(
    core: CacheCore, namespace: NamespaceId
) -> None:
    alias = canonical_alias_key(("email",), ("a@example.com",), None)
    namespace_capture = core.capture_namespace_generation(namespace)

    outcome = core.admit_unique_key_match(
        namespace_capture,
        (alias, "full"),
        "doc-1",
        "full",
        {"email": "a@example.com"},
        alias=alias,
    )

    assert outcome is AdmissionOutcome.ADMITTED
    assert core.lookup_namespace(namespace, (alias, "full")).hit is True
    assert core.lookup_identity(namespace, "doc-1", "full").hit is True
    assert core.resolve_alias(namespace, ("email",), ("a@example.com",), None) == (
        "doc-1"
    )


def test_the_published_alias_survives_so_a_later_read_takes_the_identity_path(
    core: CacheCore, namespace: NamespaceId
) -> None:
    alias = canonical_alias_key(("email",), ("a@example.com",), None)
    namespace_capture = core.capture_namespace_generation(namespace)
    core.admit_unique_key_match(
        namespace_capture,
        (alias, "full"),
        "doc-1",
        "full",
        {"email": "a@example.com"},
        alias=alias,
    )

    resolved_identity = core.resolve_alias(
        namespace, ("email",), ("a@example.com",), None
    )

    assert resolved_identity == "doc-1"
    assert core.lookup_identity(namespace, resolved_identity, "full").hit is True


def test_a_write_to_the_matched_document_invalidates_both_entries_and_the_alias(
    core: CacheCore, namespace: NamespaceId
) -> None:
    alias = canonical_alias_key(("email",), ("a@example.com",), None)
    namespace_capture = core.capture_namespace_generation(namespace)
    core.admit_unique_key_match(
        namespace_capture,
        (alias, "full"),
        "doc-1",
        "full",
        {"email": "a@example.com"},
        alias=alias,
    )

    core.record_write(namespace, "doc-1")

    assert core.lookup_identity(namespace, "doc-1", "full").hit is False
    assert core.resolve_alias(namespace, ("email",), ("a@example.com",), None) is None


@pytest.mark.parametrize(
    "invalidate",
    [
        pytest.param(
            lambda core, namespace: core.record_write(namespace, "unrelated-doc"),
            id="write",
        ),
        pytest.param(
            lambda core, namespace: core.clear_namespace(namespace), id="clear"
        ),
    ],
)
def test_an_invalidation_after_the_capture_declines_the_match_and_publishes_no_alias(
    core: CacheCore,
    namespace: NamespaceId,
    invalidate: Callable[[CacheCore, NamespaceId], None],
) -> None:
    alias = canonical_alias_key(("email",), ("a@example.com",), None)
    namespace_capture = core.capture_namespace_generation(namespace)
    invalidate(core, namespace)

    outcome = core.admit_unique_key_match(
        namespace_capture,
        (alias, "full"),
        "doc-1",
        "full",
        {"email": "a@example.com"},
        alias=alias,
    )

    assert outcome is AdmissionOutcome.DECLINED_STALE
    assert core.resolve_alias(namespace, ("email",), ("a@example.com",), None) is None
    assert core.lookup_identity(namespace, "doc-1", "full").hit is False


def test_admit_unique_key_match_declines_an_oversize_value(
    namespace: NamespaceId,
) -> None:
    core = CacheCore(CacheCoreConfig(budget_bytes=1_000, max_entry_bytes=32))
    alias = canonical_alias_key(("email",), ("a@example.com",), None)
    namespace_capture = core.capture_namespace_generation(namespace)

    outcome = core.admit_unique_key_match(
        namespace_capture,
        (alias, "full"),
        "doc-1",
        "full",
        {"payload": "x" * 100},
        alias=alias,
    )

    assert outcome is AdmissionOutcome.DECLINED_OVERSIZE
    assert core.resolve_alias(namespace, ("email",), ("a@example.com",), None) is None


def test_discard_stale_alias_removes_a_matching_alias(
    core: CacheCore, namespace: NamespaceId
) -> None:
    alias = canonical_alias_key(("email",), ("a@example.com",), None)
    namespace_capture = core.capture_namespace_generation(namespace)
    core.admit_unique_key_match(
        namespace_capture,
        (alias, "full"),
        "doc-1",
        "full",
        {"email": "a@example.com"},
        alias=alias,
    )

    core.discard_stale_alias(namespace_capture, alias, "doc-1")

    assert core.resolve_alias(namespace, ("email",), ("a@example.com",), None) is None


def test_stale_unique_key_cleanup_cannot_mutate_a_recreated_namespace(
    core: CacheCore, namespace: NamespaceId
) -> None:
    alias = canonical_alias_key(("email",), ("a@example.com",), None)
    discriminator = (alias, "full")
    old_capture = core.capture_namespace_generation(namespace)
    core.admit_unique_key_match(
        old_capture,
        discriminator,
        "doc-1",
        "full",
        {"email": "old@example.com"},
        alias=alias,
    )

    core.drop_namespace(namespace)

    new_capture = core.capture_namespace_generation(namespace)
    outcome = core.admit_unique_key_match(
        new_capture,
        discriminator,
        "doc-1",
        "full",
        {"email": "new@example.com"},
        alias=alias,
    )
    assert outcome is AdmissionOutcome.ADMITTED

    core.discard_stale_alias(old_capture, alias, "doc-1")
    core.discard_namespace_entry(old_capture, discriminator)

    assert core.resolve_alias(namespace, ("email",), ("a@example.com",), None) == (
        "doc-1"
    )
    lookup_result = core.lookup_namespace(namespace, discriminator)
    assert lookup_result.hit
    assert lookup_result.value == {"email": "new@example.com"}


def test_discard_namespace_entry_lets_a_negative_result_replace_a_stale_positive_one(
    core: CacheCore, namespace: NamespaceId
) -> None:
    alias = canonical_alias_key(("email",), ("a@example.com",), None)
    discriminator = (alias, "full")
    first_capture = core.capture_namespace_generation(namespace)
    core.admit_unique_key_match(
        first_capture, discriminator, "doc-1", "full", {"v": "old"}, alias=alias
    )
    core.discard_stale_alias(first_capture, alias, "doc-1")

    second_capture = core.capture_namespace_generation(namespace)

    core.discard_namespace_entry(second_capture, discriminator)
    outcome = core.admit_namespace(second_capture, discriminator, None)

    assert outcome is AdmissionOutcome.ADMITTED
    lookup_result = core.lookup_namespace(namespace, discriminator)
    assert lookup_result.hit
    assert lookup_result.value is None


def test_discard_namespace_entry_on_an_absent_key_is_a_no_op(
    core: CacheCore, namespace: NamespaceId
) -> None:
    capture = core.capture_namespace_generation(namespace)
    core.discard_namespace_entry(capture, ("nothing-cached-here", "full"))


def test_discard_namespace_entry_does_not_evict_a_newer_valid_entry(
    core: CacheCore, namespace: NamespaceId
) -> None:
    alias = canonical_alias_key(("email",), ("a@example.com",), None)
    discriminator = (alias, "full")
    stale_capture = core.capture_namespace_generation(namespace)
    core.record_write(namespace, "unrelated-doc")
    fresh_capture = core.capture_namespace_generation(namespace)

    outcome = core.admit_unique_key_match(
        fresh_capture, discriminator, "doc-new", "full", {"v": "new"}, alias=alias
    )
    assert outcome is AdmissionOutcome.ADMITTED

    core.discard_namespace_entry(stale_capture, discriminator)

    lookup_result = core.lookup_namespace(namespace, discriminator)
    assert lookup_result.hit
    assert lookup_result.value == {"v": "new"}


def test_discard_stale_alias_is_a_no_op_when_the_alias_was_repointed_concurrently(
    core: CacheCore, namespace: NamespaceId
) -> None:
    alias = canonical_alias_key(("email",), ("a@example.com",), None)
    first_capture = core.capture_namespace_generation(namespace)
    core.admit_unique_key_match(
        first_capture, (alias, "full"), "doc-old", "full", {"v": "old"}, alias=alias
    )
    second_capture = core.capture_namespace_generation(namespace)
    core.admit_unique_key_match(
        second_capture, (alias, "full"), "doc-new", "full", {"v": "new"}, alias=alias
    )

    core.discard_stale_alias(second_capture, alias, "doc-old")

    assert core.resolve_alias(namespace, ("email",), ("a@example.com",), None) == (
        "doc-new"
    )


def test_admit_unique_key_match_rejects_none_as_an_identity_value(
    core: CacheCore, namespace: NamespaceId
) -> None:
    alias = canonical_alias_key(("email",), ("a@example.com",), None)
    namespace_capture = core.capture_namespace_generation(namespace)

    with pytest.raises(UnsupportedCacheRequestError):
        core.admit_unique_key_match(
            namespace_capture,
            (alias, "full"),
            None,
            "full",
            {"email": "a@example.com"},
            alias=alias,
        )


@pytest.mark.parametrize(
    "unencodable_value",
    [
        pytest.param(_Unencodable(), id="unencodable_type"),
        pytest.param(10**20, id="out_of_range_int_overflow"),
    ],
)
def test_admit_unique_key_match_declines_when_the_value_cannot_be_encoded(
    core: CacheCore, namespace: NamespaceId, unencodable_value: object
) -> None:
    alias = canonical_alias_key(("email",), ("a@example.com",), None)
    namespace_capture = core.capture_namespace_generation(namespace)

    outcome = core.admit_unique_key_match(
        namespace_capture,
        (alias, "full"),
        "doc-1",
        "full",
        unencodable_value,
        alias=alias,
    )

    assert outcome is AdmissionOutcome.DECLINED_UNENCODABLE
    assert core.resolve_alias(namespace, ("email",), ("a@example.com",), None) is None


def test_a_stale_match_cannot_repoint_an_alias_published_by_a_fresher_match(
    core: CacheCore, namespace: NamespaceId
) -> None:
    alias = canonical_alias_key(("email",), ("a@example.com",), None)
    stale_capture = core.capture_namespace_generation(namespace)
    core.record_write(namespace, "doc-old")
    fresh_capture = core.capture_namespace_generation(namespace)
    outcome = core.admit_unique_key_match(
        fresh_capture,
        (alias, "full"),
        "doc-new",
        "full",
        {"v": "fresh"},
        alias=alias,
    )
    assert outcome is AdmissionOutcome.ADMITTED

    outcome = core.admit_unique_key_match(
        stale_capture, (alias, "full"), "doc-old", "full", {"v": "stale"}, alias=alias
    )

    assert outcome is AdmissionOutcome.DECLINED_STALE
    resolved_identity = core.resolve_alias(
        namespace, ("email",), ("a@example.com",), None
    )
    assert resolved_identity == "doc-new"
    lookup_result = core.lookup_identity(namespace, resolved_identity, "full")
    assert lookup_result.hit
    assert lookup_result.value == {"v": "fresh"}


def test_the_alias_survives_when_the_identity_entry_is_already_cached(
    core: CacheCore, namespace: NamespaceId
) -> None:
    alias = canonical_alias_key(("email",), ("a@example.com",), None)
    document = {"email": "a@example.com", "name": "Ada"}
    identity_capture = core.begin_identity_admission(namespace, "doc-1")
    core.admit_identity(identity_capture, "full", document)

    namespace_capture = core.capture_namespace_generation(namespace)
    core.admit_unique_key_match(
        namespace_capture, (alias, "full"), "doc-1", "full", document, alias=alias
    )

    resolved_identity = core.resolve_alias(
        namespace, ("email",), ("a@example.com",), None
    )
    assert resolved_identity == "doc-1"
    lookup_result = core.lookup_identity(namespace, resolved_identity, "full")
    assert lookup_result.hit is True
    assert lookup_result.value == document


def test_discard_stale_alias_on_an_unresolved_key_value_is_a_no_op(
    core: CacheCore, namespace: NamespaceId
) -> None:
    alias = canonical_alias_key(("email",), ("missing@example.com",), None)
    capture = core.capture_namespace_generation(namespace)

    core.discard_stale_alias(capture, alias, "doc-1")

    assert (
        core.resolve_alias(namespace, ("email",), ("missing@example.com",), None)
        is None
    )
