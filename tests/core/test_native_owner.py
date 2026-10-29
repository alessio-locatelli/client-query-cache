"""Native ownership and callback boundaries, beyond the reference implementation."""

from __future__ import annotations

import asyncio
import gc
import multiprocessing
import threading
import weakref
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Literal, NamedTuple

import pytest
from bson.int64 import Int64
from hypothesis import given, settings
from hypothesis import strategies as st
from pymongo import AsyncMongoClient, MongoClient

from client_query_cache._core.codec import encode_value
from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.find_reads import PreparedFindRead
from client_query_cache._core.keys import (
    NamespaceId,
    canonical_alias_key,
)
from client_query_cache._core.manager import CacheCore, CacheCoreConfig
from client_query_cache._shared import coordinator as shared_coordinator
from client_query_cache._shared_index import LocalCacheCore as NativeCacheCore
from client_query_cache._types import BsonDict, NonEmptyStr, NonNegativeInt
from client_query_cache.asynchronous import CacheManager as AsyncManager
from client_query_cache.synchronous import CacheManager as SyncManager

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from contextlib import AbstractContextManager
    from types import NotImplementedType

    from faker import Faker

    from client_query_cache._core.contracts import IdentityCaptureView, LocalCacheCore

pytestmark = pytest.mark.unit
_NAMESPACE = NamespaceId("native_owner", "values")
_COLLISION_HASH = 137


class Ownership(NamedTuple):
    namespaces: NonNegativeInt
    identities: NonNegativeInt
    aliases: NonNegativeInt
    captures: NonNegativeInt
    sources: NonNegativeInt


@pytest.fixture
def namespace_attribute_names(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    names: dict[str, list[str]] = defaultdict(list)
    original = NamespaceId.__getattribute__

    def observe(namespace: NamespaceId, name: str) -> object:
        names[name].append(name)
        return original(namespace, name)

    monkeypatch.setattr(NamespaceId, "__getattribute__", observe)
    return names


@pytest.mark.parametrize("field_name", ["database", "collection"])
def test_native_namespace_lookups_reuse_attribute_names(
    native: LocalCacheCore,
    namespace_attribute_names: dict[str, list[str]],
    field_name: Literal["database", "collection"],
    faker: Faker,
) -> None:
    absent_key = faker.pystr()
    for _ in range(16):
        assert not native.lookup_namespace(_NAMESPACE, absent_key).hit
    names = namespace_attribute_names[field_name]
    assert len(names) >= 16
    assert all(name is names[0] for name in names)


def ownership(core: LocalCacheCore) -> Ownership:
    return Ownership(*getattr(core, "_ownership")())  # noqa: B009 - The private diagnostic is outside the common core protocol.


@dataclass(eq=False, slots=True, weakref_slot=True)
class Key:
    value: int
    callback: Callable[[], None] | None = None
    owner: object = None

    def __hash__(self) -> int:
        return _COLLISION_HASH

    def __eq__(self, other: object) -> bool | NotImplementedType:
        if not isinstance(other, Key):
            return NotImplemented
        if self is not other and self.callback is not None:
            callback = self.callback
            self.callback = None
            callback()
        return self.value == other.value


@pytest.fixture
def native() -> Generator[LocalCacheCore]:
    with managed_core(
        NativeCacheCore,
        CacheCoreConfig(budget_bytes=256, max_entry_bytes=128),
    ) as core:
        yield core


@contextmanager
def managed_core(
    factory: type[LocalCacheCore], config: CacheCoreConfig
) -> Generator[LocalCacheCore]:
    core = factory(config)
    assert core.max_namespaces == config.max_namespaces
    try:
        yield core
    finally:
        core.close()


@dataclass(slots=True)
class Gate:
    entered: threading.Event
    proceed: threading.Event
    fail: bool = False

    def __call__(self) -> None:
        self.entered.set()
        assert self.proceed.wait(5)
        if self.fail:
            fail_comparison()


@pytest.fixture
def comparison_gate() -> Generator[tuple[Gate, ThreadPoolExecutor]]:
    gate = Gate(threading.Event(), threading.Event())
    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            yield gate, executor
        finally:
            gate.proceed.set()


def replace(core: LocalCacheCore, *, drop: bool) -> None:
    if drop:
        core.drop_namespace(_NAMESPACE)
    else:
        core.record_write(_NAMESPACE, "unrelated")
    observation = core.admit_namespace(
        core.capture_namespace_generation(_NAMESPACE), Key(1), "fresh"
    )
    assert observation is AdmissionOutcome.ADMITTED


def insert_colliding_namespace(core: LocalCacheCore) -> None:
    assert (
        core.admit_namespace(
            core.capture_namespace_generation(_NAMESPACE), Key(1), "fresh"
        )
        is AdmissionOutcome.ADMITTED
    )


@pytest.mark.parametrize("operation", ["lookup", "admission"])
def test_negative_comparison_retries_after_a_matching_key_is_inserted(
    native: LocalCacheCore, operation: str
) -> None:
    key = Key(0)
    native.admit_namespace(
        native.capture_namespace_generation(_NAMESPACE), key, "unrelated"
    )
    capture = native.capture_namespace_generation(_NAMESPACE)
    key.callback = partial(insert_colliding_namespace, native)
    if operation == "lookup":
        assert native.lookup_namespace(_NAMESPACE, Key(1)).value == "fresh"
        assert native.snapshot().misses == 0
    else:
        assert (
            native.admit_namespace(capture, Key(1), "pending")
            is AdmissionOutcome.DECLINED_STALE
        )
        assert native.lookup_namespace(_NAMESPACE, Key(1)).value == "fresh"


def insert_colliding_identity(core: LocalCacheCore) -> None:
    assert (
        core.admit_identity(
            core.begin_identity_admission(_NAMESPACE, Key(1)), None, "fresh"
        )
        is AdmissionOutcome.ADMITTED
    )


def test_negative_identity_comparison_retries_before_reserving_metadata(
    native: LocalCacheCore,
) -> None:
    key = Key(0)
    unrelated = native.begin_identity_admission(_NAMESPACE, key)
    key.callback = partial(insert_colliding_identity, native)
    pending = native.begin_identity_admission(_NAMESPACE, Key(1))
    assert (
        native.admit_identity(pending, None, "pending")
        is AdmissionOutcome.DECLINED_STALE
    )
    unrelated.release()
    assert native.lookup_identity(_NAMESPACE, Key(1), None).value == "fresh"
    assert ownership(native).identities == 1
    assert ownership(native).captures == 0


@pytest.mark.parametrize("drop", [False, True], ids=["generation", "recreation"])
def test_reentrant_comparison_retries_against_current_owner(
    native: LocalCacheCore, *, drop: bool
) -> None:
    key = Key(1)
    native.admit_namespace(native.capture_namespace_generation(_NAMESPACE), key, "old")
    key.callback = partial(replace, native, drop=drop)
    observation = native.lookup_namespace(_NAMESPACE, Key(1))
    assert observation.hit
    assert observation.value == "fresh"
    assert native.snapshot().hits == 1
    assert native.snapshot().misses == 0


def test_parallel_mutation_can_finish_while_python_equality_is_blocked(
    native: LocalCacheCore,
    comparison_gate: tuple[Gate, ThreadPoolExecutor],
) -> None:
    gate, executor = comparison_gate
    key = Key(1)
    native.admit_namespace(native.capture_namespace_generation(_NAMESPACE), key, "old")
    key.callback = gate
    pending = executor.submit(native.lookup_namespace, _NAMESPACE, Key(1))
    assert gate.entered.wait(5)
    replace(native, drop=True)
    gate.proceed.set()
    observation = pending.result(timeout=5)
    assert observation.hit
    assert observation.value == "fresh"
    assert native.snapshot().hits == 1


def fail_comparison() -> None:
    raise ValueError("opaque equality failed")


def test_failed_equality_records_no_pending_lookup(native: LocalCacheCore) -> None:
    key = Key(1)
    native.admit_namespace(native.capture_namespace_generation(_NAMESPACE), key, "old")
    before = native.snapshot()
    key.callback = fail_comparison
    with pytest.raises(ValueError, match="opaque equality failed"):
        native.lookup_namespace(_NAMESPACE, Key(1))
    assert native.snapshot() == before
    assert native.lookup_namespace(_NAMESPACE, Key(1)).value == "old"


def test_concurrent_insertion_survives_a_raising_comparison(
    comparison_gate: tuple[Gate, ThreadPoolExecutor],
) -> None:
    gate, executor = comparison_gate
    gate.fail = True
    with bounded_core("fresh") as core:
        key = Key(0)
        core.admit_namespace(core.capture_namespace_generation(_NAMESPACE), key, "old")
        key.callback = gate
        pending = executor.submit(core.lookup_namespace, _NAMESPACE, Key(1))
        assert gate.entered.wait(5)
        insert_colliding_namespace(core)
        # Retain the state before releasing the blocked equality callback.
        concurrent = core.snapshot()
        gate.proceed.set()
        with pytest.raises(ValueError, match="opaque equality failed"):
            pending.result(timeout=5)
        assert core.snapshot() == concurrent
        # Failed comparison must not promote the older colliding entry.
        core.admit_namespace(
            core.capture_namespace_generation(_NAMESPACE), Key(2), "fresh"
        )
        assert core.lookup_namespace(_NAMESPACE, Key(1)).value == "fresh"
        assert not core.lookup_namespace(_NAMESPACE, Key(0)).hit


def record_finalization(
    core: LocalCacheCore, observations: list[NonNegativeInt]
) -> None:
    observations.append(core.snapshot().entry_count)


def test_last_key_finalizer_can_reenter_the_native_owner(
    native: LocalCacheCore,
) -> None:
    observations: list[NonNegativeInt] = []
    key = Key(1)
    weakref.finalize(key, record_finalization, native, observations)
    native.admit_namespace(native.capture_namespace_generation(_NAMESPACE), key, "old")
    del key
    native.clear_namespace(_NAMESPACE)
    assert observations == [0]


@pytest.mark.parametrize("identity", [False, True], ids=["query", "identity"])
@pytest.mark.parametrize("reclaim", ["clear", "drop", "close", "evict"])
def test_last_resident_releases_original_key(
    native: LocalCacheCore, reclaim: str, *, identity: bool
) -> None:
    key = Key(1)
    reference = weakref.ref(key)
    if identity:
        capture = native.begin_identity_admission(_NAMESPACE, key)
        native.admit_identity(capture, None, "resident")
        del capture
    else:
        native.admit_namespace(
            native.capture_namespace_generation(_NAMESPACE), key, "resident"
        )
    del key
    assert reference() is not None
    if reclaim == "clear":
        native.clear_namespace(_NAMESPACE)
    elif reclaim == "drop":
        native.drop_namespace(_NAMESPACE)
    elif reclaim == "close":
        native.close()
    else:
        for index in range(20):
            native.admit_namespace(
                native.capture_namespace_generation(_NAMESPACE), index, "x" * 80
            )
    gc.collect()
    assert reference() is None


def test_abandoned_capture_releases_identity_metadata(native: LocalCacheCore) -> None:
    key = Key(1)
    reference = weakref.ref(key)
    capture = native.begin_identity_admission(_NAMESPACE, key)
    del key
    assert reference() is not None
    del capture
    gc.collect()
    assert reference() is None
    assert ownership(native) == Ownership(1, 0, 0, 0, 0)


@pytest.fixture
def controlled_gc() -> Generator[None]:
    assert gc.isenabled()
    gc.disable()
    try:
        yield
    finally:
        gc.enable()


def capture_cycle(core: LocalCacheCore, location: str) -> weakref.ReferenceType[Key]:
    key = Key(1)
    if location == "pending":
        capture = core.begin_identity_admission(_NAMESPACE, key)
    elif location == "resident":
        core.admit_identity(core.begin_identity_admission(_NAMESPACE, key), None, "old")
        capture = core.begin_identity_admission(_NAMESPACE, key)
    elif location == "alias-key":
        core.admit_identity(
            core.begin_identity_admission(_NAMESPACE, "identity"),
            None,
            "old",
            alias=canonical_alias_key(key, "value", None),
        )
        capture = core.begin_identity_admission(_NAMESPACE, "identity")
    else:
        original = Key(1)
        core.admit_identity(
            core.begin_identity_admission(_NAMESPACE, original), None, "old"
        )
        core.admit_identity(
            core.begin_identity_admission(_NAMESPACE, key),
            None,
            "old",
            alias=canonical_alias_key("field", "value", None),
        )
        capture = core.begin_identity_admission(_NAMESPACE, original)
    key.owner = capture
    return weakref.ref(key)


@pytest.mark.usefixtures("controlled_gc")
@pytest.mark.parametrize(
    "location", ["pending", "resident", "alias-key", "alias-value"]
)
def test_capture_cycle_is_reclaimed_with_a_live_core(
    native: LocalCacheCore, location: str
) -> None:
    reference = capture_cycle(native, location)
    if location != "pending":
        for index in range(20):
            native.admit_namespace(
                native.capture_namespace_generation(_NAMESPACE), index, "x" * 80
            )
    assert ownership(native).captures == 1
    gc.collect()
    assert reference() is None
    assert ownership(native) == Ownership(1, 0, 0, 0, 0)


@pytest.mark.parametrize("identity", [False, True], ids=["query", "identity"])
def test_cyclic_python_key_does_not_keep_native_owner_alive(*, identity: bool) -> None:
    core = NativeCacheCore()
    key = Key(1, owner=core)
    reference = weakref.ref(key)
    if identity:
        core.admit_identity(
            core.begin_identity_admission(_NAMESPACE, key), None, "resident"
        )
    else:
        core.admit_namespace(
            core.capture_namespace_generation(_NAMESPACE), key, "resident"
        )
    del core, key
    gc.collect()
    assert reference() is None


def replace_identity(core: LocalCacheCore) -> None:
    core.record_write(_NAMESPACE, "identity")
    assert (
        core.admit_identity(
            core.begin_identity_admission(_NAMESPACE, "identity"), Key(1), "fresh"
        )
        is AdmissionOutcome.ADMITTED
    )


def replace_unique(core: LocalCacheCore) -> None:
    core.record_write(_NAMESPACE, "old")
    assert (
        core.admit_unique_key_match(
            core.capture_namespace_generation(_NAMESPACE),
            Key(1),
            "fresh-id",
            None,
            "fresh",
            alias=canonical_alias_key("field", "value", None),
        )
        is AdmissionOutcome.ADMITTED
    )


@pytest.mark.parametrize("operation", ["identity", "namespace", "unique"])
def test_reentrant_admission_cannot_displace_fresher_data(
    native: LocalCacheCore, operation: str
) -> None:
    key = Key(1)
    if operation == "identity":
        native.admit_identity(
            native.begin_identity_admission(_NAMESPACE, "identity"), key, "old"
        )
        identity_capture = native.begin_identity_admission(_NAMESPACE, "identity")
        key.callback = partial(replace_identity, native)
        observation = native.admit_identity(identity_capture, Key(1), "stale")
        assert observation is AdmissionOutcome.DECLINED_STALE
        assert native.lookup_identity(_NAMESPACE, "identity", Key(1)).value == "fresh"
    else:
        native.admit_namespace(
            native.capture_namespace_generation(_NAMESPACE), key, "old"
        )
        namespace_capture = native.capture_namespace_generation(_NAMESPACE)
        if operation == "namespace":
            key.callback = partial(replace, native, drop=False)
            observation = native.admit_namespace(namespace_capture, Key(1), "stale")
        else:
            key.callback = partial(replace_unique, native)
            observation = native.admit_unique_key_match(
                namespace_capture,
                Key(1),
                "old-id",
                None,
                "stale",
                alias=canonical_alias_key("field", "value", None),
            )
            assert (
                native.resolve_alias(_NAMESPACE, "field", "value", None) == "fresh-id"
            )
        assert observation is AdmissionOutcome.DECLINED_STALE
        assert native.lookup_namespace(_NAMESPACE, Key(1)).value == "fresh"


def test_alias_metadata_tracks_residents_and_is_reclaimed(
    native: LocalCacheCore,
) -> None:
    for identity in range(100):
        native.admit_unique_key_match(
            native.capture_namespace_generation(_NAMESPACE),
            ("query", identity),
            identity,
            None,
            identity,
            alias=canonical_alias_key("field", identity, None),
        )
        state = ownership(native)
        assert state.captures == 0
        assert state.aliases == state.identities
        assert state.identities <= native.snapshot().entry_count
    native.clear_namespace(_NAMESPACE)
    assert ownership(native) == Ownership(1, 0, 0, 0, 0)
    assert native.snapshot().used_bytes == 0
    native.drop_namespace(_NAMESPACE)
    assert ownership(native) == Ownership(0, 0, 0, 0, 0)


@pytest.mark.parametrize(
    ("stored", "queried"),
    [(1, 1.0), (1.0, 1), (Int64(1), 1), (1, Int64(1))],
    ids=["int-double", "double-int", "int64-int", "int-int64"],
)
def test_numeric_identity_equivalence_reaches_native_storage(
    native: LocalCacheCore, stored: object, queried: object
) -> None:
    assert (
        native.admit_identity(
            native.begin_identity_admission(_NAMESPACE, stored), None, "resident"
        )
        is AdmissionOutcome.ADMITTED
    )
    assert native.lookup_identity(_NAMESPACE, queried, None).value == "resident"
    native.record_write(_NAMESPACE, queried)
    assert not native.lookup_identity(_NAMESPACE, stored, None).hit


@pytest.fixture
def one_document(faker: Faker) -> list[BsonDict]:
    return [{"_id": faker.pystr(max_chars=8), "value": faker.pystr(max_chars=8)}]


@pytest.mark.parametrize(
    "limit",
    [0, 1, -1, True, False],
    ids=["unlimited", "positive", "negative", "true", "false"],
)
def test_exact_find_preserves_limit_identity_and_decodes_complete_results(
    native: LocalCacheCore, one_document: list[BsonDict], limit: int
) -> None:
    shape = PreparedFindRead("single-match", limit)
    assert (
        native.admit_namespace(
            native.capture_namespace_generation(_NAMESPACE),
            shape.discriminator,
            one_document,
            find_source=shape.source,
        )
        is AdmissionOutcome.ADMITTED
    )
    assert native.lookup_find(_NAMESPACE, shape).value == one_document


def test_namespace_capacity_reuse_does_not_revive_an_untracked_capture() -> None:
    with managed_core(NativeCacheCore, CacheCoreConfig(max_namespaces=1)) as core:
        core.capture_namespace_generation(_NAMESPACE)
        other = NamespaceId(_NAMESPACE.database, "other")
        untracked = core.capture_namespace_generation(other)
        assert core.try_current_epoch(other) is None
        core.drop_namespace(_NAMESPACE)
        assert (
            core.admit_namespace(
                core.capture_namespace_generation(other), None, "fresh"
            )
            is AdmissionOutcome.ADMITTED
        )
        assert (
            core.admit_namespace(untracked, None, "old")
            is AdmissionOutcome.DECLINED_STALE
        )
        assert core.lookup_namespace(other, None).value == "fresh"
        assert core.namespaces_for_database(other.database) == [other]


def test_compatible_find_promotes_source_and_reclaims_family_metadata() -> None:
    with bounded_core([0]) as core:
        first, second, third = (
            PreparedFindRead(name, 100) for name in ("first", "second", "third")
        )
        for shape in (first, second):
            core.admit_namespace(
                core.capture_namespace_generation(_NAMESPACE),
                shape.discriminator,
                [0],
                find_source=shape.source,
            )
        assert core.lookup_find(_NAMESPACE, PreparedFindRead("first", 10)).hit
        core.admit_namespace(
            core.capture_namespace_generation(_NAMESPACE),
            third.discriminator,
            [0],
            find_source=third.source,
        )
        assert core.lookup_find(_NAMESPACE, PreparedFindRead("first", 10)).hit
        assert not core.lookup_find(_NAMESPACE, PreparedFindRead("second", 10)).hit
        assert ownership(core).sources == 2
        core.record_write(_NAMESPACE, 0)
        assert ownership(core).sources == 0
        assert core.snapshot().entry_count == 2
        assert not core.lookup_find(_NAMESPACE, PreparedFindRead("first", 10)).hit
        core.close()
        assert ownership(core) == Ownership(0, 0, 0, 0, 0)
        assert core.snapshot().lifecycle == "closed"
        assert core.snapshot().entry_count == 0


def bounded_core(value: object) -> AbstractContextManager[LocalCacheCore]:
    weight = len(encode_value(value))
    return managed_core(
        NativeCacheCore,
        CacheCoreConfig(budget_bytes=weight * 2, max_entry_bytes=weight),
    )


async def async_construction() -> bool:
    async with (
        AsyncMongoClient[BsonDict](connect=False) as client,
        AsyncManager(client) as manager,
    ):
        return (
            isinstance(manager.cache_core, NativeCacheCore)
            and manager._coordinator._cache is manager.cache_core
        )


def construction_probe() -> tuple[bool, bool, bool]:
    with MongoClient[BsonDict](connect=False) as client, SyncManager(client) as manager:
        synchronous = (
            isinstance(manager.cache_core, NativeCacheCore)
            and manager._coordinator._cache is manager.cache_core
        )
    return (
        synchronous,
        asyncio.run(async_construction()),
        shared_coordinator.CacheCore is CacheCore,  # type: ignore[attr-defined] # The private imported constructor is intentionally inspected.
    )


@pytest.fixture
def spawned_worker() -> Generator[ProcessPoolExecutor]:
    with ProcessPoolExecutor(
        max_workers=1, mp_context=multiprocessing.get_context("spawn")
    ) as pool:
        yield pool


def test_spawned_native_construction_is_shared_by_managers_and_coordinators(
    spawned_worker: ProcessPoolExecutor,
) -> None:
    assert spawned_worker.submit(construction_probe).result(timeout=15) == (
        True,
        True,
        True,
    )


@pytest.mark.parametrize("operation", ["identity", "namespace"])
def test_capture_from_dropped_namespace_cannot_target_reused_slot(
    native: LocalCacheCore, operation: str
) -> None:
    old_identity = native.begin_identity_admission(_NAMESPACE, "id")
    old_namespace = native.capture_namespace_generation(_NAMESPACE)
    native.drop_namespace(_NAMESPACE)
    if operation == "identity":
        fresh_identity = native.begin_identity_admission(_NAMESPACE, "id")
        assert (
            native.admit_identity(fresh_identity, None, "fresh")
            is AdmissionOutcome.ADMITTED
        )
        assert (
            native.admit_identity(old_identity, None, "old")
            is AdmissionOutcome.DECLINED_STALE
        )
        assert native.lookup_identity(_NAMESPACE, "id", None).value == "fresh"
    else:
        fresh_namespace = native.capture_namespace_generation(_NAMESPACE)
        assert (
            native.admit_namespace(fresh_namespace, "query", "fresh")
            is AdmissionOutcome.ADMITTED
        )
        assert (
            native.admit_namespace(old_namespace, "query", "old")
            is AdmissionOutcome.DECLINED_STALE
        )
        assert native.lookup_namespace(_NAMESPACE, "query").value == "fresh"


_OPERATIONS = st.lists(
    st.tuples(
        st.sampled_from(
            [
                "admit",
                "lookup",
                "identity",
                "read",
                "write",
                "clear",
                "drop",
                "index",
                "availability",
            ]
        ),
        st.integers(min_value=-3, max_value=3),
        st.integers(min_value=-10, max_value=10),
    ),
    min_size=1,
    max_size=100,
)


def apply(core: LocalCacheCore, operation: str, key: int, value: int) -> object:
    if operation == "admit":
        return core.admit_namespace(
            core.capture_namespace_generation(_NAMESPACE), Key(key), value
        )
    if operation == "lookup":
        return core.lookup_namespace(_NAMESPACE, Key(key))
    if operation == "identity":
        return core.admit_identity(
            core.begin_identity_admission(_NAMESPACE, Key(key)), "shape", value
        )
    if operation == "read":
        return core.lookup_identity(_NAMESPACE, Key(key), "shape")
    if operation == "write":
        core.record_write(_NAMESPACE, Key(key))
    elif operation == "clear":
        core.clear_namespace(_NAMESPACE)
    elif operation == "drop":
        core.drop_namespace(_NAMESPACE)
    elif operation == "index":
        core.record_index_change(_NAMESPACE)
    else:
        core.set_database_available(_NAMESPACE.database, available=value >= 0)
    return None


@settings(max_examples=100, deadline=None)
@given(operations=_OPERATIONS)
def test_native_matches_reference_across_collision_and_eviction_schedules(
    operations: list[tuple[str, int, int]],
) -> None:
    with matching_cores() as (reference, native):
        for operation, key, value in operations:
            assert apply(native, operation, key, value) == apply(
                reference, operation, key, value
            )
            assert native.snapshot() == reference.snapshot()


@contextmanager
def matching_cores() -> Generator[tuple[LocalCacheCore, LocalCacheCore]]:
    config = CacheCoreConfig(budget_bytes=128, max_entry_bytes=64)
    with (
        managed_core(CacheCore, config) as reference,
        managed_core(NativeCacheCore, config) as native,
    ):
        yield reference, native


@pytest.fixture(params=[CacheCore, NativeCacheCore], ids=["reference", "native"])
def pinned_alias(
    request: pytest.FixtureRequest,
    faker: Faker,
) -> Generator[tuple[LocalCacheCore, NonEmptyStr, NonEmptyStr, IdentityCaptureView]]:
    identity = faker.uuid4()
    value = faker.pystr(min_chars=30, max_chars=30)
    weight = len(encode_value(value))
    with managed_core(
        request.param, CacheCoreConfig(budget_bytes=weight, max_entry_bytes=weight)
    ) as core:
        alias = canonical_alias_key("code", identity, None)
        for _ in range(2):
            core.admit_identity(
                core.begin_identity_admission(_NAMESPACE, identity),
                None,
                value,
                alias=alias,
            )
        capture = core.begin_identity_admission(_NAMESPACE, identity)
        yield core, identity, value, capture
        capture.release()


def test_capture_keeps_alias_alive_after_last_entry_eviction(
    pinned_alias: tuple[LocalCacheCore, NonEmptyStr, NonEmptyStr, IdentityCaptureView],
) -> None:
    core, identity, value, capture = pinned_alias
    core.admit_namespace(
        core.capture_namespace_generation(_NAMESPACE), "pressure", value
    )
    assert core.lookup_identity_encoded(_NAMESPACE, identity, None) is None
    assert core.resolve_alias(_NAMESPACE, "code", identity, None) == identity
    capture.release()
    assert core.resolve_alias(_NAMESPACE, "code", identity, None) is None


@pytest.fixture
def key_sizing_calls(monkeypatch: pytest.MonkeyPatch) -> list[Key]:
    calls: list[Key] = []

    def measure(key: Key) -> NonNegativeInt:
        calls.append(key)
        return object.__sizeof__(key)

    monkeypatch.setattr(Key, "__sizeof__", measure)
    return calls


@pytest.fixture
def one_slot_native() -> Generator[LocalCacheCore]:
    with managed_core(
        NativeCacheCore, CacheCoreConfig(max_entries=1, max_key_bytes=1024)
    ) as core:
        yield core


def test_native_fallback_retry_does_not_repeat_sizing_or_decline_events(
    one_slot_native: LocalCacheCore,
    key_sizing_calls: list[Key],
) -> None:
    core = one_slot_native
    other = NamespaceId("native_owner", "other")
    before = core.capture_namespace_generation(other).generation
    key = Key(1)
    assert (
        core.admit_namespace(core.capture_namespace_generation(_NAMESPACE), key, 1)
        is AdmissionOutcome.ADMITTED
    )
    key_sizing_calls.clear()
    key.callback = partial(core.record_write, other, "unrelated")
    probe = Key(1)
    assert (
        core.admit_unique_key_match(
            core.capture_namespace_generation(_NAMESPACE),
            probe,
            "A",
            "full",
            1,
            alias=canonical_alias_key("email", "alice@example.com", None),
        )
        is AdmissionOutcome.ADMITTED
    )
    assert core.capture_namespace_generation(other).generation > before
    assert key_sizing_calls == [probe]
    assert [
        (item.kind, item.reason, item.count)
        for item in core.snapshot().retention_declines
        if item.count
    ] == [("alias", "entry_capacity", 1)]
