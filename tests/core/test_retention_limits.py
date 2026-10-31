from __future__ import annotations

import sys
import threading
import weakref
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from client_query_cache import RetentionDeclineReason, RetentionRecordKind
from client_query_cache._core.canonical import canonicalize
from client_query_cache._core.codec import encode_value
from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.find_reads import find_read_shape
from client_query_cache._core.keys import NamespaceId, canonical_alias_key
from client_query_cache._core.lru import WeightedLru
from client_query_cache._core.manager import CacheCore, CacheCoreConfig
from client_query_cache._shared_index import LocalCacheCore
from client_query_cache._types import NonNegativeInt, PositiveInt

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from client_query_cache._core.contracts import LocalCacheCore as Core
    from client_query_cache._core.keys import CacheKey

    type CoreFactory = Callable[[CacheCoreConfig], Core]

pytestmark = pytest.mark.unit


@pytest.fixture(params=[CacheCore, LocalCacheCore], ids=["reference", "native"])
def core_factory(request: pytest.FixtureRequest) -> Generator[CoreFactory]:
    cores: list[Core] = []

    def create(config: CacheCoreConfig) -> Core:
        core: Core = request.param(config)
        cores.append(core)
        return core

    yield create
    for core in cores:
        core.close()


def decline_count(
    core: Core, kind: RetentionRecordKind, reason: RetentionDeclineReason
) -> NonNegativeInt:
    return next(
        record.count
        for record in core.snapshot().retention_declines
        if record.kind is kind and record.reason is reason
    )


@pytest.mark.parametrize(
    "maximum", [None, 1, 2, 3], ids=["disabled", "one", "two", "three"]
)
@pytest.mark.parametrize("key_limit", [None, 1024])
def test_unique_match_retains_a_useful_representation(
    core_factory: CoreFactory,
    namespace: NamespaceId,
    maximum: PositiveInt | None,
    key_limit: PositiveInt | None,
) -> None:
    core = core_factory(CacheCoreConfig(max_entries=maximum, max_key_bytes=key_limit))
    assert core.max_entries == maximum
    alias = canonical_alias_key("email", "alice@example.com", None)
    discriminator = (alias, "full")
    document = {"_id": "alice", "value": 1}
    outcome = core.admit_unique_key_match(
        core.capture_namespace_generation(namespace),
        discriminator,
        "alice",
        "full",
        document,
        alias=alias,
    )
    assert outcome is AdmissionOutcome.ADMITTED
    snapshot = core.snapshot()
    assert snapshot.entry_count == (2 if maximum is None else 1)
    assert snapshot.alias_count == (0 if maximum == 1 else 1)
    assert snapshot.used_bytes == len(encode_value(document)) * snapshot.entry_count
    assert core.lookup_namespace(namespace, discriminator).hit is (
        maximum is None or maximum == 1
    )
    assert core.lookup_identity(namespace, "alice", "full").hit is (maximum != 1)


def test_full_cache_does_not_evict_an_extra_value_for_an_alias(
    core_factory: CoreFactory, namespace: NamespaceId
) -> None:
    core = core_factory(CacheCoreConfig(max_entries=2))
    for discriminator in ("oldest", "newer"):
        assert (
            core.admit_namespace(
                core.capture_namespace_generation(namespace), discriminator, 1
            )
            is AdmissionOutcome.ADMITTED
        )
    alias = canonical_alias_key("email", "alice@example.com", None)
    assert (
        core.admit_unique_key_match(
            core.capture_namespace_generation(namespace),
            "query",
            "alice",
            "full",
            {"v": 1},
            alias=alias,
        )
        is AdmissionOutcome.ADMITTED
    )
    assert not core.lookup_namespace(namespace, "oldest").hit
    assert core.lookup_namespace(namespace, "newer").hit
    assert core.lookup_namespace(namespace, "query").hit
    assert core.snapshot().alias_count == 0
    assert core.snapshot().evictions == 1


def test_count_capacity_is_shared_across_namespaces(
    core_factory: CoreFactory, namespace: NamespaceId, other_namespace: NamespaceId
) -> None:
    core = core_factory(CacheCoreConfig(max_entries=1))
    for target in (namespace, other_namespace, namespace):
        assert (
            core.admit_namespace(core.capture_namespace_generation(target), "query", 1)
            is AdmissionOutcome.ADMITTED
        )
        assert core.snapshot().entry_count + core.snapshot().alias_count == 1
    assert not core.lookup_namespace(other_namespace, "query").hit


def test_large_key_declines_without_reclassifying_the_miss(
    core_factory: CoreFactory, namespace: NamespaceId
) -> None:
    core = core_factory(CacheCoreConfig(max_key_bytes=1024))
    capture = core.capture_namespace_generation(namespace)
    assert (
        core.admit_namespace(capture, "x" * 4096, 1)
        is AdmissionOutcome.DECLINED_RETENTION
    )
    assert core.snapshot().entry_count == 0
    assert core.snapshot().bypasses == 0
    assert core.snapshot().oversized_bypasses == 0
    assert (
        decline_count(
            core,
            RetentionRecordKind.NAMESPACE_VALUE,
            RetentionDeclineReason.KEY_SIZE_LIMIT,
        )
        == 1
    )


class SizedKey:
    __slots__ = ("callback",)

    def __init__(self) -> None:
        self.callback: Callable[[], object] | None = None

    def __sizeof__(self) -> NonNegativeInt:
        if self.callback is not None:
            self.callback()
        return object.__sizeof__(self)


def fail_sizing() -> None:
    raise ValueError("sizing callback failed")


@pytest.fixture
def sized_key() -> SizedKey:
    return SizedKey()


@pytest.mark.parametrize("existing", [False, True])
def test_raising_size_callback_declines_only_retention(
    core_factory: CoreFactory,
    namespace: NamespaceId,
    sized_key: SizedKey,
    *,
    existing: bool,
) -> None:
    core = core_factory(CacheCoreConfig(max_key_bytes=1024))
    if existing:
        assert (
            core.admit_namespace(
                core.capture_namespace_generation(namespace), sized_key, 1
            )
            is AdmissionOutcome.ADMITTED
        )
    sized_key.callback = fail_sizing
    assert (
        core.admit_namespace(core.capture_namespace_generation(namespace), sized_key, 2)
        is AdmissionOutcome.DECLINED_RETENTION
    )
    assert (
        decline_count(
            core,
            RetentionRecordKind.NAMESPACE_VALUE,
            RetentionDeclineReason.KEY_SIZE_UNAVAILABLE,
        )
        == 1
    )

    assert core.snapshot().entry_count == int(existing)
    if existing:
        assert core.lookup_namespace(namespace, sized_key).value == 1


def test_reentrant_sizing_rechecks_the_capture(
    core_factory: CoreFactory, namespace: NamespaceId, sized_key: SizedKey
) -> None:
    core = core_factory(CacheCoreConfig(max_entries=2, max_key_bytes=1024))
    capture = core.capture_namespace_generation(namespace)
    sized_key.callback = partial(core.record_write, namespace, "other-document")
    assert (
        core.admit_namespace(capture, sized_key, 1) is AdmissionOutcome.DECLINED_STALE
    )
    assert core.snapshot().entry_count == 0
    assert sum(record.count for record in core.snapshot().retention_declines) == 0


@pytest.mark.parametrize("maximum", [None, 512])
def test_hits_and_disabled_admissions_do_not_size_keys(
    core_factory: CoreFactory,
    namespace: NamespaceId,
    sized_key: SizedKey,
    maximum: PositiveInt | None,
) -> None:
    core = core_factory(CacheCoreConfig(max_key_bytes=maximum))
    assert (
        core.admit_namespace(core.capture_namespace_generation(namespace), sized_key, 1)
        is AdmissionOutcome.ADMITTED
    )
    sizing = Mock(side_effect=fail_sizing)
    sized_key.callback = sizing
    for _ in range(3):
        assert core.lookup_namespace(namespace, sized_key).value == 1
        core.snapshot()
    if maximum is None:
        assert (
            core.admit_namespace(
                core.capture_namespace_generation(namespace), (sized_key, "later"), 2
            )
            is AdmissionOutcome.ADMITTED
        )
    assert sum(record.count for record in core.snapshot().retention_declines) == 0

    sizing.assert_not_called()


@pytest.mark.parametrize("difference", [-1, 0, 1])
def test_key_charge_boundary_and_tuple_identity_deduplication(
    core_factory: CoreFactory, namespace: NamespaceId, difference: int
) -> None:
    subtree = canonicalize(("a distinct predicate value", 42))
    key = canonicalize((subtree, subtree))
    assert isinstance(subtree, tuple)
    assert isinstance(key, tuple)
    # The same subtree and scalar identities contribute once within this record.
    charge = sum(
        sys.getsizeof(node) for node in (key, key[1], subtree, subtree[1], *subtree[1])
    )
    core = core_factory(CacheCoreConfig(max_key_bytes=charge + difference))
    outcome = core.admit_namespace(core.capture_namespace_generation(namespace), key, 1)
    assert outcome is (
        AdmissionOutcome.DECLINED_RETENTION
        if difference < 0
        else AdmissionOutcome.ADMITTED
    )


@pytest.mark.parametrize("max_entries", [None, 1, 2, 3])
def test_alias_only_decline_keeps_identity_and_bypass_meanings(
    core_factory: CoreFactory, namespace: NamespaceId, max_entries: PositiveInt | None
) -> None:
    core = core_factory(CacheCoreConfig(max_entries=max_entries, max_key_bytes=1024))
    alias = canonical_alias_key("email", "x" * 4096, None)
    capture = core.begin_identity_admission(namespace, "document")
    assert (
        core.admit_identity(capture, "full", 1, alias=alias)
        is AdmissionOutcome.ADMITTED
    )
    assert core.lookup_identity(namespace, "document", "full").value == 1
    assert core.resolve_alias(namespace, "email", "x" * 4096, None) is None
    snapshot = core.snapshot()
    assert snapshot.bypasses == snapshot.oversized_bypasses == 0
    assert (
        decline_count(
            core, RetentionRecordKind.ALIAS, RetentionDeclineReason.KEY_SIZE_LIMIT
        )
        == 1
    )


@pytest.mark.parametrize("maximum", [1, 2, 3])
@pytest.mark.parametrize("key_limit", [None, 1024])
def test_unique_replacement_and_lifecycle_release_capacity(
    core_factory: CoreFactory,
    namespace: NamespaceId,
    maximum: PositiveInt,
    key_limit: PositiveInt | None,
) -> None:
    core = core_factory(CacheCoreConfig(max_entries=maximum, max_key_bytes=key_limit))
    alias = canonical_alias_key("email", "alice@example.com", None)
    for identity in ("A", "B", "B"):
        capture = core.capture_namespace_generation(namespace)
        assert (
            core.admit_unique_key_match(
                capture, "query", identity, "full", identity, alias=alias
            )
            is AdmissionOutcome.ADMITTED
        )
        assert core.snapshot().entry_count + core.snapshot().alias_count <= maximum
    core.drop_namespace(namespace)
    assert core.snapshot().entry_count == core.snapshot().alias_count == 0
    assert (
        core.admit_namespace(core.capture_namespace_generation(namespace), "new", 1)
        is AdmissionOutcome.ADMITTED
    )
    core.close()
    assert core.snapshot().entry_count == core.snapshot().alias_count == 0


@pytest.mark.parametrize("maximum", [1, 2])
def test_unique_pair_uses_one_payload_budget(
    core_factory: CoreFactory, namespace: NamespaceId, maximum: PositiveInt
) -> None:
    document = {"v": "document"}
    weight = len(encode_value(document))
    core = core_factory(
        CacheCoreConfig(
            budget_bytes=weight, max_entry_bytes=weight, max_entries=maximum
        )
    )
    alias = canonical_alias_key("email", "alice@example.com", None)
    assert (
        core.admit_unique_key_match(
            core.capture_namespace_generation(namespace),
            "query",
            "A",
            "full",
            document,
            alias=alias,
        )
        is AdmissionOutcome.ADMITTED
    )
    assert core.snapshot().used_bytes == weight
    assert core.snapshot().alias_count == maximum - 1


@pytest.mark.parametrize("maximum", [1, 2, 3])
def test_concurrent_cross_namespace_admissions_obey_the_global_bound(
    core_factory: CoreFactory,
    namespace: NamespaceId,
    other_namespace: NamespaceId,
    admission_pool: ThreadPoolExecutor,
    maximum: PositiveInt,
) -> None:
    core = core_factory(CacheCoreConfig(max_entries=maximum))
    barrier = threading.Barrier(2)
    futures = [
        admission_pool.submit(admit_after_barrier, core, target, barrier, index)
        for index, target in enumerate((namespace, other_namespace))
    ]
    assert all(
        future.result(timeout=10) is AdmissionOutcome.ADMITTED for future in futures
    )
    assert core.snapshot().entry_count + core.snapshot().alias_count <= maximum


@pytest.fixture
def admission_pool() -> Generator[ThreadPoolExecutor]:
    with ThreadPoolExecutor(max_workers=2) as pool:
        yield pool


def admit_after_barrier(
    core: Core,
    namespace: NamespaceId,
    barrier: threading.Barrier,
    identity: NonNegativeInt,
) -> AdmissionOutcome:
    capture = core.capture_namespace_generation(namespace)
    alias = canonical_alias_key("email", str(identity), None)
    barrier.wait(timeout=10)
    return core.admit_unique_key_match(
        capture, "query", identity, "full", identity, alias=alias
    )


@given(
    operations=st.lists(
        st.tuples(
            st.sampled_from(("identity", "namespace", "unique", "write", "clear")),
            st.integers(0, 1),
            st.integers(0, 3),
        ),
        min_size=1,
        max_size=60,
    )
)
@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_generated_operation_orders_preserve_capacity_and_fresh_hits(
    core_factory: CoreFactory,
    operations: list[tuple[str, NonNegativeInt, NonNegativeInt]],
) -> None:
    # The fixture is a factory: each generated example obtains its own core.
    core = core_factory(CacheCoreConfig(max_entries=3, max_key_bytes=2048))
    namespaces = [NamespaceId("generated", name) for name in ("a", "b")]
    versions = [[0] * 4 for _ in namespaces]
    generations = [0, 0]
    for operation, namespace_index, identity in operations:
        namespace = namespaces[namespace_index]
        value = versions[namespace_index][identity]
        if operation == "write":
            versions[namespace_index][identity] += 1
            generations[namespace_index] += 1
            core.record_write(namespace, identity)
        elif operation == "clear":
            core.clear_namespace(namespace)
            generations[namespace_index] += 1
            versions[namespace_index] = [item + 1 for item in versions[namespace_index]]
        elif operation == "identity":
            core.admit_identity(
                core.begin_identity_admission(namespace, identity), "full", value
            )
        elif operation == "namespace":
            core.admit_namespace(
                core.capture_namespace_generation(namespace),
                "query",
                generations[namespace_index],
            )
        else:
            alias = canonical_alias_key("unique", identity, None)
            core.admit_unique_key_match(
                core.capture_namespace_generation(namespace),
                ("unique", identity),
                identity,
                "full",
                value,
                alias=alias,
            )
        snapshot = core.snapshot()
        assert snapshot.entry_count + snapshot.alias_count <= 3
        for index, target in enumerate(namespaces):
            query = core.lookup_namespace(target, "query")
            if query.hit:
                assert query.value == generations[index]
            for candidate in range(4):
                identity_lookup = core.lookup_identity(target, candidate, "full")
                if identity_lookup.hit:
                    assert identity_lookup.value == versions[index][candidate]


@pytest.mark.parametrize("maximum", [None, 1, 2])
@pytest.mark.parametrize(
    "large_record", ["identity", "alias", "namespace", "identity-and-namespace"]
)
def test_composite_key_declines_and_fallback_observations(
    core_factory: CoreFactory,
    namespace: NamespaceId,
    maximum: PositiveInt | None,
    large_record: str,
) -> None:
    core = core_factory(CacheCoreConfig(max_entries=maximum, max_key_bytes=1024))
    identity = "I" * (4096 if "identity" in large_record else 1)
    discriminator = "Q" * (4096 if "namespace" in large_record else 1)
    alias_value = "A" * (4096 if large_record == "alias" else 1)
    alias = canonical_alias_key("unique", alias_value, None)
    outcome = core.admit_unique_key_match(
        core.capture_namespace_generation(namespace),
        discriminator,
        identity,
        "full",
        1,
        alias=alias,
    )
    namespace_fits = "namespace" not in large_record
    pair_fits = (
        maximum != 1 and "identity" not in large_record and large_record != "alias"
    )
    if maximum is None:
        assert outcome is (
            AdmissionOutcome.ADMITTED
            if namespace_fits and "identity" not in large_record
            else AdmissionOutcome.DECLINED_RETENTION
        )
    else:
        assert outcome is (
            AdmissionOutcome.ADMITTED
            if pair_fits or namespace_fits
            else AdmissionOutcome.DECLINED_RETENTION
        )
    snapshot = core.snapshot()
    assert snapshot.bypasses == snapshot.oversized_bypasses == 0
    assert snapshot.entry_count == (
        (int(namespace_fits) + int("identity" not in large_record))
        if maximum is None
        else int(pair_fits or namespace_fits)
    )
    assert snapshot.alias_count == int(pair_fits)
    if maximum == 1:
        assert (
            decline_count(
                core, RetentionRecordKind.ALIAS, RetentionDeclineReason.ENTRY_CAPACITY
            )
            == 1
        )
    elif "identity" in large_record:
        assert (
            decline_count(
                core,
                RetentionRecordKind.IDENTITY_VALUE,
                RetentionDeclineReason.KEY_SIZE_LIMIT,
            )
            == 1
        )
    elif large_record == "alias":
        assert (
            decline_count(
                core, RetentionRecordKind.ALIAS, RetentionDeclineReason.KEY_SIZE_LIMIT
            )
            == 1
        )


@pytest.mark.parametrize("maximum", [1, 2])
def test_alias_capacity_decline_never_evicts_an_extra_value(
    core_factory: CoreFactory,
    namespace: NamespaceId,
    maximum: PositiveInt,
) -> None:
    core = core_factory(CacheCoreConfig(max_entries=maximum))
    if maximum == 2:
        assert (
            core.admit_namespace(
                core.capture_namespace_generation(namespace), "other", 1
            )
            is AdmissionOutcome.ADMITTED
        )
    alias = canonical_alias_key("email", "alice@example.com", None)
    assert (
        core.admit_identity(
            core.begin_identity_admission(namespace, "A"), "full", 1, alias=alias
        )
        is AdmissionOutcome.ADMITTED
    )
    assert core.snapshot().entry_count == maximum
    assert core.snapshot().alias_count == core.snapshot().evictions == 0
    assert (
        decline_count(
            core, RetentionRecordKind.ALIAS, RetentionDeclineReason.ENTRY_CAPACITY
        )
        == 1
    )


def test_oldest_alias_reclamation_preserves_resident_values(
    core_factory: CoreFactory,
    namespace: NamespaceId,
) -> None:
    core = core_factory(CacheCoreConfig(max_entries=3))
    alias = canonical_alias_key("email", "alice@example.com", None)
    assert (
        core.admit_identity(
            core.begin_identity_admission(namespace, "A"), "full", 1, alias=alias
        )
        is AdmissionOutcome.ADMITTED
    )
    for key in ("first", "second"):
        assert (
            core.admit_namespace(core.capture_namespace_generation(namespace), key, 1)
            is AdmissionOutcome.ADMITTED
        )
    assert core.lookup_identity(namespace, "A", "full").value == 1
    assert core.snapshot().entry_count == 3
    assert core.snapshot().alias_count == core.snapshot().evictions == 0


@pytest.mark.parametrize("pinned", [False, True])
def test_last_value_eviction_and_capture_release_reclaim_alias_ownership(
    core_factory: CoreFactory,
    namespace: NamespaceId,
    pinned: bool,
) -> None:
    weight = len(encode_value(1))
    core = core_factory(
        CacheCoreConfig(max_entries=5, budget_bytes=weight, max_entry_bytes=weight)
    )
    alias = canonical_alias_key("email", "alice@example.com", None)
    assert (
        core.admit_identity(
            core.begin_identity_admission(namespace, "A"), "full", 1, alias=alias
        )
        is AdmissionOutcome.ADMITTED
    )
    capture = core.begin_identity_admission(namespace, "A")
    if not pinned:
        capture.release()
    assert (
        core.admit_namespace(core.capture_namespace_generation(namespace), "other", 2)
        is AdmissionOutcome.ADMITTED
    )
    assert core.snapshot().entry_count == 1
    assert core.snapshot().alias_count == int(pinned)
    capture.release()
    assert core.snapshot().alias_count == 0


@pytest.fixture
def reference_core() -> Generator[CacheCore]:
    core = CacheCore(CacheCoreConfig(max_entries=2, max_key_bytes=2048))
    yield core
    core.close()


@pytest.fixture(params=["selection", "commit", "reuse"])
def recency_race(
    request: pytest.FixtureRequest,
    reference_core: CacheCore,
    namespace: NamespaceId,
    admission_pool: ThreadPoolExecutor,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[str]:
    for key in ("old", "new"):
        reference_core.admit_namespace(
            reference_core.capture_namespace_generation(namespace), key, 1
        )
    phase: str = request.param
    method = "next_planned" if phase == "selection" else "commit_plan"
    original = getattr(WeightedLru, method)
    ready = threading.Event()
    release = threading.Event()
    original_touch = WeightedLru.touch

    def pause_touch(lru: WeightedLru, key: CacheKey) -> None:
        ready.set()
        assert release.wait(timeout=10)
        original_touch(lru, key)

    monkeypatch.setattr(WeightedLru, "touch", pause_touch)
    warm = admission_pool.submit(reference_core.lookup_namespace, namespace, "old")
    assert ready.wait(timeout=10)
    fired = False

    def promote(lru: WeightedLru, *arguments: object) -> object:
        nonlocal fired
        if not fired:
            fired = True
            release.set()
            assert warm.result(timeout=10).hit
        return original(lru, *arguments)

    monkeypatch.setattr(WeightedLru, method, promote)
    yield phase
    release.set()
    warm.result(timeout=10)


def test_reference_transaction_replans_after_a_concurrent_warm_promotion(
    reference_core: CacheCore,
    namespace: NamespaceId,
    recency_race: str,
    sized_key: SizedKey,
) -> None:
    sizing = Mock()
    sized_key.callback = sizing
    discriminator = "old" if recency_race == "reuse" else sized_key
    assert (
        reference_core.admit_namespace(
            reference_core.capture_namespace_generation(namespace), discriminator, 1
        )
        is AdmissionOutcome.ADMITTED
    )
    assert reference_core.lookup_namespace(namespace, "old").hit
    assert reference_core.lookup_namespace(namespace, "new").hit is (
        recency_race == "reuse"
    )
    assert reference_core.snapshot().entry_count == 2
    assert sizing.call_count == (0 if recency_race == "reuse" else 1)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class FinalizerKey:
    value: int


def record_reference_finalization(core: CacheCore, observations: list[bool]) -> None:
    core._guard.assert_outside_storage()
    observations.append(not getattr(core._availability_lock, "_is_owned")())  # noqa: B009 - CPython lock ownership is outside the public RLock stubs.


@pytest.fixture
def retiring_core() -> Generator[CacheCore]:
    weight = len(encode_value(1))
    core = CacheCore(
        CacheCoreConfig(max_entries=4, budget_bytes=weight, max_entry_bytes=weight)
    )
    yield core
    core.close()


@pytest.mark.parametrize("action", ["replace", "write", "release"])
def test_equal_alias_identity_finalizers_run_after_the_capacity_transaction(
    retiring_core: CacheCore,
    namespace: NamespaceId,
    action: str,
) -> None:
    core = retiring_core
    core.admit_identity(
        core.begin_identity_admission(namespace, FinalizerKey(1)), "full", 1
    )
    identity = FinalizerKey(1)
    observations: list[bool] = []
    weakref.finalize(identity, record_reference_finalization, core, observations)
    alias = canonical_alias_key("email", "alice@example.com", None)
    assert (
        core.admit_identity(
            core.begin_identity_admission(namespace, identity), "full", 1, alias=alias
        )
        is AdmissionOutcome.ADMITTED
    )
    del identity
    assert not observations
    if action == "replace":
        core.admit_identity(
            core.begin_identity_admission(namespace, FinalizerKey(1)),
            "full",
            1,
            alias=alias,
        )
    elif action == "write":
        core.record_write(namespace, FinalizerKey(1))
    else:
        capture = core.begin_identity_admission(namespace, FinalizerKey(1))
        core.admit_namespace(core.capture_namespace_generation(namespace), "filler", 1)
        capture.release()
    assert observations == [True]


@pytest.mark.parametrize("maximum", [1, 2])
def test_unique_policy_does_not_size_unused_representations(
    core_factory: CoreFactory,
    namespace: NamespaceId,
    sized_key: SizedKey,
    maximum: PositiveInt,
) -> None:
    core = core_factory(CacheCoreConfig(max_entries=maximum, max_key_bytes=2048))
    sizing = Mock(side_effect=fail_sizing)
    sized_key.callback = sizing
    alias = canonical_alias_key("email", "alice@example.com", None)
    assert (
        core.admit_unique_key_match(
            core.capture_namespace_generation(namespace),
            sized_key if maximum == 2 else "query",
            sized_key if maximum == 1 else "A",
            "full",
            1,
            alias=alias,
        )
        is AdmissionOutcome.ADMITTED
    )
    assert core.snapshot().entry_count == 1
    assert core.snapshot().alias_count == maximum - 1
    assert sum(record.count for record in core.snapshot().retention_declines) == (
        1 if maximum == 1 else 0
    )

    sizing.assert_not_called()


def populate_other_namespace(core: Core, namespace: NamespaceId) -> None:
    assert (
        core.admit_namespace(core.capture_namespace_generation(namespace), "other", 1)
        is AdmissionOutcome.ADMITTED
    )


def test_reentrant_alias_sizing_uses_current_cross_namespace_occupancy(
    core_factory: CoreFactory,
    namespace: NamespaceId,
    other_namespace: NamespaceId,
    sized_key: SizedKey,
) -> None:
    core = core_factory(CacheCoreConfig(max_entries=2, max_key_bytes=2048))
    sized_key.callback = partial(populate_other_namespace, core, other_namespace)
    alias = canonical_alias_key("email", sized_key, None)
    assert (
        core.admit_unique_key_match(
            core.capture_namespace_generation(namespace),
            "query",
            "A",
            "full",
            1,
            alias=alias,
        )
        is AdmissionOutcome.ADMITTED
    )
    assert core.lookup_namespace(namespace, "query").value == 1
    assert core.lookup_namespace(other_namespace, "other").value == 1
    assert core.snapshot().evictions == core.snapshot().alias_count == 0
    assert (
        decline_count(
            core, RetentionRecordKind.ALIAS, RetentionDeclineReason.ENTRY_CAPACITY
        )
        == 1
    )


def test_alias_republication_refreshes_reclamation_order_in_both_cores(
    core_factory: CoreFactory,
    namespace: NamespaceId,
) -> None:
    core = core_factory(CacheCoreConfig(max_entries=4))
    aliases = [
        canonical_alias_key("email", value, None)
        for value in ("first", "second", "first")
    ]
    for alias in aliases:
        assert (
            core.admit_identity(
                core.begin_identity_admission(namespace, "A"), "full", 1, alias=alias
            )
            is AdmissionOutcome.ADMITTED
        )
    for key in ("old", "new"):
        core.admit_namespace(core.capture_namespace_generation(namespace), key, 1)
    assert core.resolve_alias(namespace, "email", "first", None) == "A"
    assert core.resolve_alias(namespace, "email", "second", None) is None
    assert core.snapshot().entry_count + core.snapshot().alias_count == 4


def test_replacement_planning_skips_already_removed_values(
    core_factory: CoreFactory,
    namespace: NamespaceId,
) -> None:
    weight = len(encode_value(1))
    core = core_factory(
        CacheCoreConfig(
            max_entries=3, budget_bytes=3 * weight, max_entry_bytes=3 * weight
        )
    )
    core.admit_identity(core.begin_identity_admission(namespace, "A"), "full", 1)
    for key in ("query", "other"):
        core.admit_namespace(core.capture_namespace_generation(namespace), key, 1)
    core.record_write(namespace, "A")
    payload = b"x" * (3 * weight - len(encode_value(b"")))
    assert (
        core.admit_unique_key_match(
            core.capture_namespace_generation(namespace),
            "query",
            "A",
            "full",
            payload,
            alias=canonical_alias_key("email", "alice@example.com", None),
        )
        is AdmissionOutcome.ADMITTED
    )
    assert core.snapshot().entry_count == core.snapshot().alias_count == 1
    assert core.snapshot().used_bytes == 3 * weight
    assert core.snapshot().evictions == 1


def test_bson_eviction_deduplicates_aliases_already_reclaimed_for_count(
    core_factory: CoreFactory,
    namespace: NamespaceId,
) -> None:
    weight = len(encode_value(1))
    core = core_factory(
        CacheCoreConfig(
            max_entries=4, budget_bytes=3 * weight, max_entry_bytes=3 * weight
        )
    )
    for value in ("first", "second"):
        core.admit_identity(
            core.begin_identity_admission(namespace, "B"),
            "full",
            1,
            alias=canonical_alias_key("email", value, None),
        )
    core.admit_namespace(core.capture_namespace_generation(namespace), "other", 1)
    payload = b"x" * (3 * weight - len(encode_value(b"")))
    assert (
        core.admit_namespace(
            core.capture_namespace_generation(namespace), "new", payload
        )
        is AdmissionOutcome.ADMITTED
    )
    assert core.snapshot().entry_count == 1
    assert core.snapshot().alias_count == 0
    assert core.snapshot().used_bytes == 3 * weight


def prepared_admission(
    core: Core, namespace: NamespaceId, kind: str, value: object
) -> Callable[[], AdmissionOutcome]:
    if kind == "identity":
        return partial(
            core.admit_identity,
            core.begin_identity_admission(namespace, "A"),
            "full",
            value,
        )
    capture = core.capture_namespace_generation(namespace)
    if kind == "namespace":
        return partial(core.admit_namespace, capture, "query", value)
    return partial(
        core.admit_unique_key_match,
        capture,
        "query",
        "A",
        "full",
        value,
        alias=canonical_alias_key("email", "alice@example.com", None),
    )


@pytest.mark.parametrize("maximum", [None, 2])
@pytest.mark.parametrize("kind", ["namespace", "identity", "unique"])
@pytest.mark.parametrize("event", ["write", "drop", "unavailable", "oversize"])
def test_retention_preflight_preserves_existing_admission_guards(
    core_factory: CoreFactory,
    namespace: NamespaceId,
    maximum: PositiveInt | None,
    kind: str,
    event: str,
) -> None:
    core = core_factory(
        CacheCoreConfig(
            max_entries=maximum,
            max_key_bytes=1024,
            budget_bytes=1024,
            max_entry_bytes=128,
        )
    )
    value = b"x" * 4096 if event == "oversize" else 1
    admit = prepared_admission(core, namespace, kind, value)
    if event == "write":
        core.record_write(namespace, "A")
    elif event == "drop":
        core.drop_namespace(namespace)
    elif event == "unavailable":
        core.set_database_available(namespace.database, available=False)
    expected = (
        AdmissionOutcome.DECLINED_OVERSIZE
        if event == "oversize"
        else AdmissionOutcome.DECLINED_UNAVAILABLE
        if event == "unavailable"
        else AdmissionOutcome.DECLINED_STALE
    )
    assert admit() is expected
    assert core.snapshot().entry_count == core.snapshot().alias_count == 0
    assert sum(record.count for record in core.snapshot().retention_declines) == 0


def write_on_another_thread(
    pool: ThreadPoolExecutor, core: Core, namespace: NamespaceId
) -> None:
    pool.submit(core.record_write, namespace, "A").result(timeout=10)


def test_key_sizing_allows_concurrent_invalidation_without_holding_core_locks(
    core_factory: CoreFactory,
    namespace: NamespaceId,
    sized_key: SizedKey,
    admission_pool: ThreadPoolExecutor,
) -> None:
    core = core_factory(CacheCoreConfig(max_entries=2, max_key_bytes=2048))
    capture = core.capture_namespace_generation(namespace)
    sized_key.callback = partial(
        write_on_another_thread, admission_pool, core, namespace
    )
    assert (
        core.admit_namespace(capture, sized_key, 1) is AdmissionOutcome.DECLINED_STALE
    )
    assert core.snapshot().entry_count == 0


def publish_newer_result(core: Core, namespace: NamespaceId, key: SizedKey) -> None:
    key.callback = None
    core.record_write(namespace, "A")
    assert (
        core.admit_namespace(core.capture_namespace_generation(namespace), key, 2)
        is AdmissionOutcome.ADMITTED
    )


@pytest.mark.parametrize("composite", [False, True])
def test_invalidated_sizing_cannot_remove_a_newer_namespace_replacement(
    core_factory: CoreFactory,
    namespace: NamespaceId,
    sized_key: SizedKey,
    *,
    composite: bool,
) -> None:
    core = core_factory(CacheCoreConfig(max_entries=2, max_key_bytes=2048))
    capture = core.capture_namespace_generation(namespace)
    sized_key.callback = partial(publish_newer_result, core, namespace, sized_key)
    if composite:
        outcome = core.admit_unique_key_match(
            capture,
            sized_key,
            sized_key,
            "full",
            1,
            alias=canonical_alias_key("email", "alice@example.com", None),
        )
    else:
        outcome = core.admit_namespace(capture, sized_key, 1)
    assert outcome is AdmissionOutcome.DECLINED_STALE
    assert core.lookup_namespace(namespace, sized_key).value == 2
    assert core.snapshot().entry_count == 1
    assert core.snapshot().alias_count == 0


@pytest.mark.parametrize("maximum", [None, 2])
@pytest.mark.parametrize("kind", ["namespace", "identity"])
def test_individual_key_declines_preserve_existing_residency(
    core_factory: CoreFactory,
    namespace: NamespaceId,
    maximum: PositiveInt | None,
    kind: str,
) -> None:
    core = core_factory(CacheCoreConfig(max_entries=maximum, max_key_bytes=1024))
    core.admit_namespace(core.capture_namespace_generation(namespace), "kept", 1)
    if kind == "identity":
        outcome = core.admit_identity(
            core.begin_identity_admission(namespace, "x" * 4096), "full", 2
        )
    else:
        outcome = core.admit_namespace(
            core.capture_namespace_generation(namespace), "x" * 4096, 2
        )
    assert outcome is AdmissionOutcome.DECLINED_RETENTION
    assert core.lookup_namespace(namespace, "kept").value == 1
    assert core.snapshot().entry_count == 1
    assert sum(record.count for record in core.snapshot().retention_declines) == 1


def test_count_limited_find_sources_remain_available_to_prefix_reads(
    core_factory: CoreFactory,
    namespace: NamespaceId,
) -> None:
    core = core_factory(CacheCoreConfig(max_entries=2))
    source = find_read_shape({}, None, {"_id": 1}, 0, 0, collation=None, codec="codec")
    request = find_read_shape({}, None, {"_id": 1}, 0, 1, collation=None, codec="codec")
    assert (
        core.admit_namespace(
            core.capture_namespace_generation(namespace),
            source.discriminator,
            [{"_id": 1}, {"_id": 2}],
            find_source=source.source,
        )
        is AdmissionOutcome.ADMITTED
    )
    assert core.lookup_find(namespace, request).value == [{"_id": 1}]
    assert core.snapshot().entry_count == 1


@pytest.mark.parametrize("maximum", [None, 2])
@pytest.mark.parametrize("composite", [False, True])
def test_repeated_identity_admission_records_each_declined_alias(
    core_factory: CoreFactory,
    namespace: NamespaceId,
    maximum: PositiveInt | None,
    *,
    composite: bool,
) -> None:
    core = core_factory(CacheCoreConfig(max_entries=maximum, max_key_bytes=1024))
    assert (
        core.admit_identity(core.begin_identity_admission(namespace, "A"), "full", 1)
        is AdmissionOutcome.ADMITTED
    )
    alias = canonical_alias_key("email", "x" * 4096, None)
    if composite:
        outcome = core.admit_unique_key_match(
            core.capture_namespace_generation(namespace),
            "query",
            "A",
            "full",
            1,
            alias=alias,
        )
    else:
        outcome = core.admit_identity(
            core.begin_identity_admission(namespace, "A"), "full", 1, alias=alias
        )
    assert outcome is (
        AdmissionOutcome.DECLINED_STALE
        if maximum is None
        else AdmissionOutcome.ADMITTED
    )
    assert core.snapshot().entry_count == 1 + int(composite)
    assert core.snapshot().alias_count == 0
    assert (
        decline_count(
            core, RetentionRecordKind.ALIAS, RetentionDeclineReason.KEY_SIZE_LIMIT
        )
        == 1
    )


@pytest.mark.parametrize("maximum", [None, 2])
@pytest.mark.parametrize("blocked", ["identity", "namespace"])
def test_key_only_composite_declines_keep_legacy_duplicate_outcomes(
    core_factory: CoreFactory,
    namespace: NamespaceId,
    maximum: PositiveInt | None,
    blocked: str,
) -> None:
    core = core_factory(CacheCoreConfig(max_entries=maximum, max_key_bytes=1024))
    discriminator = "x" * 4096 if blocked == "namespace" else "query"
    identity = "x" * 4096 if blocked == "identity" else "A"
    if blocked == "identity":
        assert (
            core.admit_namespace(
                core.capture_namespace_generation(namespace), discriminator, 1
            )
            is AdmissionOutcome.ADMITTED
        )
    else:
        assert (
            core.admit_identity(
                core.begin_identity_admission(namespace, identity), "full", 1
            )
            is AdmissionOutcome.ADMITTED
        )
    outcome = core.admit_unique_key_match(
        core.capture_namespace_generation(namespace),
        discriminator,
        identity,
        "full",
        1,
        alias=canonical_alias_key("email", "alice@example.com", None),
    )
    assert outcome is (
        AdmissionOutcome.DECLINED_STALE
        if maximum is None
        else AdmissionOutcome.ADMITTED
    )
    assert core.snapshot().entry_count == 1
    assert sum(record.count for record in core.snapshot().retention_declines) == int(
        maximum is None or blocked == "identity"
    )
