from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.keys import NamespaceId, canonical_alias_key

if TYPE_CHECKING:
    from collections.abc import Callable

    from client_query_cache._core.entries import LookupResult
    from client_query_cache._core.manager import CacheCore

pytestmark = pytest.mark.unit


def _seed_identity(core: CacheCore, namespace: NamespaceId) -> None:
    capture = core.begin_identity_admission(namespace, "doc-1")
    core.admit_identity(capture, "full", {"v": "current"})


def _seed_namespace(core: CacheCore, namespace: NamespaceId) -> None:
    capture = core.capture_namespace_generation(namespace)
    core.admit_namespace(capture, ("find", {}), ["current"])


def _seed_alias(core: CacheCore, namespace: NamespaceId) -> None:
    alias = canonical_alias_key("email", "a@example.com", None)
    capture = core.begin_identity_admission(namespace, "doc-1")
    core.admit_identity(capture, "full", {"v": "current"}, alias=alias)


_LOOKUPS = [
    pytest.param(
        _seed_identity,
        lambda core, namespace: core.lookup_identity(namespace, "doc-1", "full"),
        id="lookup_identity",
    ),
    pytest.param(
        _seed_namespace,
        lambda core, namespace: core.lookup_namespace(namespace, ("find", {})),
        id="lookup_namespace",
    ),
    pytest.param(
        _seed_alias,
        lambda core, namespace: core.lookup_by_alias(
            namespace, "email", "a@example.com", None, "full"
        ),
        id="lookup_by_alias",
    ),
]

_ADMISSIONS = [
    pytest.param(
        lambda core, namespace: core.admit_identity(
            core.begin_identity_admission(namespace, "doc-1"), "full", {"v": "x"}
        ),
        id="admit_identity",
    ),
    pytest.param(
        lambda core, namespace: core.admit_namespace(
            core.capture_namespace_generation(namespace), ("find", {}), ["x"]
        ),
        id="admit_namespace",
    ),
]


def _start_identity_admission(
    core: CacheCore, namespace: NamespaceId
) -> Callable[[], AdmissionOutcome]:
    capture = core.begin_identity_admission(namespace, "doc-1")
    return lambda: core.admit_identity(capture, "full", {"v": "x"})


def _start_namespace_admission(
    core: CacheCore, namespace: NamespaceId
) -> Callable[[], AdmissionOutcome]:
    capture = core.capture_namespace_generation(namespace)
    return lambda: core.admit_namespace(capture, ("find", {}), ["x"])


_START_ADMISSIONS = [
    pytest.param(_start_identity_admission, id="admit_identity"),
    pytest.param(_start_namespace_admission, id="admit_namespace"),
]


@pytest.mark.parametrize(("seed", "lookup"), _LOOKUPS)
def test_lookups_are_unaffected_by_default(
    core: CacheCore,
    namespace: NamespaceId,
    seed: Callable[[CacheCore, NamespaceId], None],
    lookup: Callable[[CacheCore, NamespaceId], LookupResult],
) -> None:
    seed(core, namespace)
    assert lookup(core, namespace).hit


@pytest.mark.parametrize(("seed", "lookup"), _LOOKUPS)
def test_lookups_are_bypassed_while_the_database_is_unavailable(
    core: CacheCore,
    namespace: NamespaceId,
    seed: Callable[[CacheCore, NamespaceId], None],
    lookup: Callable[[CacheCore, NamespaceId], LookupResult],
) -> None:
    seed(core, namespace)
    core.set_database_available(namespace.database, available=False)

    assert lookup(core, namespace).hit is False
    assert core.snapshot().bypasses == 1


@pytest.mark.parametrize("admit", _ADMISSIONS)
def test_admissions_are_declined_while_the_database_is_unavailable(
    core: CacheCore,
    namespace: NamespaceId,
    admit: Callable[[CacheCore, NamespaceId], AdmissionOutcome],
) -> None:
    core.set_database_available(namespace.database, available=False)

    assert admit(core, namespace) is AdmissionOutcome.DECLINED_UNAVAILABLE
    assert core.snapshot().bypasses == 1


@pytest.mark.parametrize("start_admission", _START_ADMISSIONS)
def test_admissions_started_while_unavailable_are_declined_after_recovery(
    core: CacheCore,
    namespace: NamespaceId,
    start_admission: Callable[[CacheCore, NamespaceId], Callable[[], AdmissionOutcome]],
) -> None:
    core.set_database_available(namespace.database, available=False)
    admit = start_admission(core, namespace)
    core.set_database_available(namespace.database, available=True)

    assert admit() is AdmissionOutcome.DECLINED_UNAVAILABLE
    assert core.snapshot().bypasses == 1


@pytest.mark.parametrize("start_admission", _START_ADMISSIONS)
def test_admissions_spanning_recovery_are_declined(
    core: CacheCore,
    namespace: NamespaceId,
    start_admission: Callable[[CacheCore, NamespaceId], Callable[[], AdmissionOutcome]],
) -> None:
    admit = start_admission(core, namespace)
    core.set_database_available(namespace.database, available=False)
    core.set_database_available(namespace.database, available=True)

    assert admit() is AdmissionOutcome.DECLINED_UNAVAILABLE
    assert core.snapshot().bypasses == 1


def test_availability_can_be_restored(core: CacheCore, namespace: NamespaceId) -> None:
    core.set_database_available(namespace.database, available=False)
    core.set_database_available(namespace.database, available=True)

    capture = core.begin_identity_admission(namespace, "doc-1")
    outcome = core.admit_identity(capture, "full", {"v": "x"})

    assert outcome is AdmissionOutcome.ADMITTED
    assert core.lookup_identity(namespace, "doc-1", "full").hit


def test_resolve_alias_is_bypassed_while_the_database_is_unavailable(
    core: CacheCore, namespace: NamespaceId
) -> None:
    _seed_alias(core, namespace)
    core.set_database_available(namespace.database, available=False)

    resolved = core.resolve_alias(namespace, "email", "a@example.com", None)

    assert resolved is None
    assert core.snapshot().bypasses == 1


def test_marking_one_database_unavailable_does_not_affect_another(
    core: CacheCore, namespace: NamespaceId
) -> None:
    other_database_namespace = NamespaceId("other_db", namespace.collection)
    core.set_database_available(namespace.database, available=False)

    capture = core.begin_identity_admission(other_database_namespace, "doc-1")
    outcome = core.admit_identity(capture, "full", {"v": "x"})

    assert outcome is AdmissionOutcome.ADMITTED
    assert core.lookup_identity(other_database_namespace, "doc-1", "full").hit
