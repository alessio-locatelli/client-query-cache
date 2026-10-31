from __future__ import annotations

import hashlib
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pymongo import MongoClient

import client_query_cache
from benchmarks.public_shared_cache import (
    _implementation,
    await_admissions,
    in_predicate,
    reconcile_admissions,
)
from client_query_cache import CacheManager
from client_query_cache._types import BsonDict, NonNegativeFloat, NonNegativeInt
from research.native_local_integration.registration import (
    NATIVE_CORE,
    PYTHON_CORE,
    REGISTRATIONS,
    Build,
    build,
    verify_core,
    verify_installation,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from faker import Faker

    from client_query_cache._shared.attachment import Message

pytestmark = pytest.mark.unit

_EXPECTED_ADMISSIONS = 3
_RESIDENT_ENTRIES = 5
_SOURCE_ROOT = Path(client_query_cache.__file__).parents[1]


def _owner(
    admissions: NonNegativeInt,
    entries: NonNegativeInt,
    *,
    rejected: NonNegativeInt = 0,
    evictions: NonNegativeInt = 0,
) -> Message:
    return {
        "counters": {
            "admissions": admissions,
            "admitted": admissions - rejected,
            "rejected_admissions": rejected,
        },
        "cache": {"entry_count": entries, "evictions": evictions},
    }


def _observer(*observations: Message) -> Callable[[Message], Message | None]:
    remaining = iter(observations)

    def observe(message: Message) -> Message | None:
        assert message == {"op": "observe"}
        return next(remaining)

    return observe


@pytest.mark.parametrize("label", tuple(REGISTRATIONS["native-internals"].builds))
def test_current_builds_expect_their_installed_native_core(label: str) -> None:
    expected = build("native-internals", label)
    assert expected.core == NATIVE_CORE
    with (
        MongoClient[BsonDict](connect=False) as client,
        CacheManager(client) as manager,
    ):
        verify_core(expected, _implementation(manager), _SOURCE_ROOT)


@pytest.mark.parametrize(("label", "core"), [("M", PYTHON_CORE), ("F", NATIVE_CORE)])
def test_historical_registration_keeps_its_revision_expectations(
    label: str, core: str
) -> None:
    assert build("pr-355", label).core == core


def test_an_unregistered_label_is_rejected() -> None:
    with pytest.raises(ValueError, match="'C' is not a registered"):
        build("native-internals", "C")


@pytest.mark.parametrize(
    ("expected", "prefix", "match"),
    [
        (Build(PYTHON_CORE, ""), _SOURCE_ROOT, "expected .*CacheCore"),
        (Build(NATIVE_CORE, ""), _SOURCE_ROOT / "absent", "is outside"),
    ],
)
def test_mismatched_core_provenance_is_rejected(
    expected: Build, prefix: Path, match: str
) -> None:
    with (
        MongoClient[BsonDict](connect=False) as client,
        CacheManager(client) as manager,
        pytest.raises(ValueError, match=match),
    ):
        verify_core(expected, _implementation(manager), prefix)


@pytest.fixture
def installed_wheel(tmp_path: Path, faker: Faker) -> tuple[Build, Path, Path]:
    package = tmp_path / "site-packages" / "client_query_cache"
    (package / "_core").mkdir(parents=True)
    members = {
        "__init__.py": faker.binary(length=64),
        "_core/codec.py": faker.binary(length=64),
        "_shared_index.abi3.so": faker.binary(length=256),
    }
    wheel = tmp_path / "client_query_cache.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("client_query_cache-0.0.0.dist-info/RECORD", b"")
        for name, content in members.items():
            archive.writestr(f"client_query_cache/{name}", content)
            (package / name).write_bytes(content)
    expected = Build(NATIVE_CORE, hashlib.sha256(wheel.read_bytes()).hexdigest())
    return expected, wheel, package


def test_an_installation_matching_its_registered_wheel_is_accepted(
    installed_wheel: tuple[Build, Path, Path],
) -> None:
    verify_installation(*installed_wheel)


@pytest.mark.parametrize(
    ("member", "match"),
    [("_shared_index.abi3.so", "differs from"), ("_core/codec.py", "differs from")],
)
def test_an_installation_differing_from_its_wheel_is_rejected(
    installed_wheel: tuple[Build, Path, Path], member: str, match: str, faker: Faker
) -> None:
    expected, wheel, package = installed_wheel
    (package / member).write_bytes(faker.binary(length=32))
    with pytest.raises(ValueError, match=match):
        verify_installation(expected, wheel, package)


def test_a_missing_installed_file_is_rejected(
    installed_wheel: tuple[Build, Path, Path],
) -> None:
    expected, wheel, package = installed_wheel
    (package / "__init__.py").unlink()
    with pytest.raises(ValueError, match="differs from"):
        verify_installation(expected, wheel, package)


def test_an_unregistered_wheel_is_rejected(
    installed_wheel: tuple[Build, Path, Path],
) -> None:
    expected, wheel, package = installed_wheel
    with pytest.raises(ValueError, match=r"expected 0+$"):
        verify_installation(replace(expected, wheel_sha256="0" * 64), wheel, package)


def test_the_preparation_variant_uses_the_full_registered_predicate() -> None:
    predicate = in_predicate()
    assert predicate == {"$in": list(range(256))}
    assert predicate is not in_predicate()
    assert predicate["$in"] is not in_predicate()["$in"]


def test_completed_admissions_are_reported_with_their_drain() -> None:
    drained = await_admissions(
        _observer(
            _owner(0, 2),
            _owner(_EXPECTED_ADMISSIONS - 1, _RESIDENT_ENTRIES - 1),
            _owner(_EXPECTED_ADMISSIONS, _RESIDENT_ENTRIES),
        ),
        _owner(0, 2),
        _EXPECTED_ADMISSIONS,
        _RESIDENT_ENTRIES,
    )
    assert drained["polls"] == 3
    assert drained["processed"] == drained["admitted"] == _EXPECTED_ADMISSIONS
    assert drained["entries"] == _RESIDENT_ENTRIES
    assert drained["rejected"] == drained["evictions"] == 0


def test_incomplete_admissions_fail_at_the_drain_deadline() -> None:
    pending = _owner(_EXPECTED_ADMISSIONS - 1, _RESIDENT_ENTRIES - 1)
    with pytest.raises(TimeoutError, match="completed 2 of 3 admissions"):
        await_admissions(
            lambda _message: pending,
            _owner(0, 2),
            _EXPECTED_ADMISSIONS,
            _RESIDENT_ENTRIES,
            timeout=0.05,
        )


@pytest.mark.parametrize(
    "observed",
    [
        _owner(_EXPECTED_ADMISSIONS + 1, _RESIDENT_ENTRIES),
        _owner(_EXPECTED_ADMISSIONS, _RESIDENT_ENTRIES, rejected=1),
        _owner(_EXPECTED_ADMISSIONS, _RESIDENT_ENTRIES, evictions=1),
    ],
    ids=["unexpected-admission", "rejected", "evicting"],
)
def test_unregistered_admission_outcomes_fail(observed: Message) -> None:
    with pytest.raises(AssertionError):
        await_admissions(
            _observer(observed),
            _owner(0, 2),
            _EXPECTED_ADMISSIONS,
            _RESIDENT_ENTRIES,
        )


def _worker_counters(
    one_way: NonNegativeInt, queued: NonNegativeInt, *, dropped: NonNegativeInt = 0
) -> dict[str, NonNegativeInt]:
    return {
        "one_way": one_way,
        "native_admissions": queued,
        "native_admission_drops": 0,
        "dropped_one_way": dropped,
    }


def test_queued_identity_admissions_reconcile_with_owner_processing() -> None:
    drain: dict[str, NonNegativeFloat] = {"processed": _EXPECTED_ADMISSIONS}
    reconcile_admissions(
        "identity",
        drain,
        _worker_counters(_EXPECTED_ADMISSIONS, _EXPECTED_ADMISSIONS),
    )
    assert drain["worker_submitted"] == drain["worker_queued"] == _EXPECTED_ADMISSIONS


@pytest.mark.parametrize(
    ("method", "worker"),
    [
        ("identity", {}),
        ("identity", _worker_counters(_EXPECTED_ADMISSIONS, 0)),
        ("find", _worker_counters(_EXPECTED_ADMISSIONS - 1, 0)),
        ("find", _worker_counters(_EXPECTED_ADMISSIONS, 0, dropped=1)),
    ],
    ids=["no-diagnostics", "socket-fallback", "unprocessed", "dropped"],
)
def test_unreconciled_admissions_fail(
    method: str, worker: dict[str, NonNegativeInt]
) -> None:
    with pytest.raises(AssertionError):
        reconcile_admissions(method, {"processed": _EXPECTED_ADMISSIONS}, worker)
