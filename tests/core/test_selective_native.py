from __future__ import annotations

import gc
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier
from typing import TYPE_CHECKING

from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    invariant,
    precondition,
    rule,
    run_state_machine_as_test,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterator

    from client_query_cache._core.contracts import NamespaceCaptureView

import pytest

from client_query_cache import CacheCore, CacheCoreConfig, SelectiveInvalidation
from client_query_cache._core.canonical import canonicalize
from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.find_reads import PreparedFindRead
from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.selective_invalidation import (
    normalize_invalidation,
    partition_scalar,
)
from client_query_cache._types import NonNegativeInt, PositiveInt

pytestmark = pytest.mark.unit


@contextmanager
def configured_core(max_entries: PositiveInt | None = None) -> Generator[CacheCore]:
    owner = CacheCore(
        CacheCoreConfig(max_entries=max_entries),
        invalidation=normalize_invalidation(
            {
                ("example", "posts"): SelectiveInvalidation(
                    insert_partition_field="author_id",
                    update_dependencies_for_counts=True,
                )
            }
        ),
    )
    owner.set_database_available("example", available=True)
    try:
        yield owner
    finally:
        owner.close()


@pytest.fixture
def core() -> Iterator[CacheCore]:
    with configured_core() as owner:
        yield owner


@pytest.fixture(params=[None, 1], ids=["unbounded-records", "one-record"])
def bounded_core(request: pytest.FixtureRequest) -> Iterator[CacheCore]:
    with configured_core(request.param) as owner:
        yield owner


@pytest.mark.parametrize(
    ("partition", "dependencies", "event", "retained"),
    [
        (42, ("author_id",), "other-insert", True),
        (42, ("author_id",), "matching-insert", False),
        (42, ("author_id",), "other-update", True),
        (42, ("author_id",), "matching-update", False),
        (42, None, "other-update", False),
        (None, ("author_id",), "other-insert", False),
        (42, ("author_id",), "unclassified", False),
        (42, (), "other-update", True),
    ],
)
def test_native_selective_lookup_and_admission_share_write_proofs(
    core: CacheCore,
    partition: object,
    dependencies: tuple[str, ...] | None,
    event: str,
    retained: bool,
) -> None:
    namespace = NamespaceId("example", "posts")
    capture = core.capture_namespace_generation(
        namespace, partition=partition_scalar(partition), dependencies=dependencies
    )
    assert core.admit_namespace(capture, "count", 3) is AdmissionOutcome.ADMITTED
    ordinary = core.capture_namespace_generation(namespace)
    assert core.admit_namespace(ordinary, "ordinary", 4) is AdmissionOutcome.ADMITTED
    if event == "other-insert":
        core.record_write(namespace, 1, partition=partition_scalar(99))
    elif event == "matching-insert":
        core.record_write(namespace, 1, partition=partition_scalar(42))
    elif event == "other-update":
        core.record_write(namespace, 1, changed_paths=["views"])
    elif event == "matching-update":
        core.record_write(namespace, 1, changed_paths=["author_id"])
    else:
        core.record_write(namespace, 1)
    assert core.lookup_namespace(namespace, "count").hit is retained
    assert not core.lookup_namespace(namespace, "ordinary").hit
    assert core.admit_namespace(capture, "racing", 3) is (
        AdmissionOutcome.ADMITTED if retained else AdmissionOutcome.DECLINED_STALE
    )
    capture.release()


@pytest.mark.parametrize(
    "transition",
    ["clear_namespace", "drop_namespace", "record_index_change", "create_namespace"],
)
def test_native_selective_lifecycle_fences(core: CacheCore, transition: str) -> None:
    namespace = NamespaceId("example", "posts")
    capture = core.capture_namespace_generation(
        namespace, partition=partition_scalar(42)
    )
    core.admit_namespace(capture, "count", 3)
    getattr(core, transition)(namespace)
    assert not core.lookup_namespace(namespace, "count").hit
    assert core.admit_namespace(capture, "racing", 3) is AdmissionOutcome.DECLINED_STALE
    capture.release()


@pytest.mark.parametrize(
    ("partition", "dependencies"),
    [
        (b"x" * 82, None),
        (None, tuple(f"field_{index}" for index in range(33))),
        (None, ("é" * 33,)),
        (None, ("nested.0",)),
    ],
)
def test_native_boundary_rejects_unbounded_or_ambiguous_descriptors(
    core: CacheCore,
    partition: bytes | None,
    dependencies: tuple[str, ...] | None,
) -> None:
    namespace = NamespaceId("example", "posts")
    capture = core.capture_namespace_generation(
        namespace, partition=partition, dependencies=dependencies
    )
    core.record_write(namespace, 1, partition=partition_scalar(99))
    assert core.admit_namespace(capture, "count", 1) is AdmissionOutcome.DECLINED_STALE
    capture.release()


@pytest.mark.parametrize("invalidated", [False, True], ids=["current", "obsolete"])
def test_capture_capacity_is_global_and_abandoned_owners_release_slots(
    bounded_core: CacheCore, invalidated: bool
) -> None:
    owner = bounded_core
    namespace = NamespaceId("example", "posts")
    captures = [
        owner.capture_namespace_generation(namespace, partition=partition_scalar(index))
        for index in range(1023)
    ]
    if invalidated:
        owner.record_write(namespace, 1)
    barrier = Barrier(2)

    def acquire(index: PositiveInt) -> NamespaceCaptureView:
        barrier.wait()
        return owner.capture_namespace_generation(
            NamespaceId("example", str(index)), partition=partition_scalar(index)
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        final_captures = list(executor.map(acquire, (2000, 2001)))
    for index, capture in enumerate(final_captures):
        owner.admit_namespace(capture, "count", index)
        owner.record_write(capture.namespace, 1, partition=partition_scalar(9999))
    # With a one-record cache limit, probe each acquisition through admission again.
    outcomes = [
        owner.admit_namespace(capture, "probe", 1) for capture in final_captures
    ]
    assert outcomes.count(AdmissionOutcome.DECLINED_STALE) == 1
    final_captures.clear()
    captures.clear()
    del capture
    gc.collect()
    replacement = owner.capture_namespace_generation(
        namespace, partition=partition_scalar(9999)
    )
    owner.record_write(namespace, 1, partition=partition_scalar(9998))
    assert owner.admit_namespace(replacement, "new", 1) is AdmissionOutcome.ADMITTED
    replacement.release()


@pytest.mark.parametrize("max_entries", [None, 2048], ids=["unbounded", "bounded"])
@pytest.mark.parametrize(
    "event", ["update", "unknown", "index"], ids=["update", "unknown", "index"]
)
@pytest.mark.parametrize("find", [False, True], ids=["count", "find"])
def test_obsolete_residents_do_not_exhaust_selective_capacity(
    max_entries: PositiveInt | None, event: str, find: bool
) -> None:
    namespace = NamespaceId("example", "posts")
    with configured_core(max_entries) as owner:
        for partition in range(1024):
            capture = owner.capture_namespace_generation(
                namespace,
                partition=partition_scalar(partition),
                dependencies=None if find else ("author_id",),
            )
            source = PreparedFindRead(canonicalize(partition), 2)
            assert (
                owner.admit_namespace(
                    capture,
                    source.discriminator,
                    [partition],
                    find_source=source.source if find else None,
                )
                is AdmissionOutcome.ADMITTED
            )
            capture.release()
        if event == "update":
            owner.record_write(namespace, 1, changed_paths=["author_id"])
        elif event == "index":
            owner.record_index_change(namespace)
        else:
            owner.record_write(namespace, 1)
        replacement = owner.capture_namespace_generation(
            namespace, partition=partition_scalar(2048)
        )
        owner.record_write(namespace, 1, partition=partition_scalar(4096))
        assert (
            owner.admit_namespace(replacement, "replacement", 1)
            is AdmissionOutcome.ADMITTED
        )
        replacement.release()
        assert owner.lookup_namespace(namespace, "replacement").value == 1
        for partition in range(1024):
            source = PreparedFindRead(canonicalize(partition), 2)
            assert not owner.lookup_namespace(namespace, source.discriminator).hit
            if find:
                assert not owner.lookup_find(
                    namespace, PreparedFindRead(source.family, 1)
                ).hit
            capture = owner.capture_namespace_generation(namespace)
            assert (
                owner.admit_namespace(capture, source.discriminator, [partition])
                is AdmissionOutcome.ADMITTED
            )
        assert owner.lookup_namespace(namespace, "replacement").value == 1


def test_retiring_obsolete_rows_preserves_current_resident_ownership(
    core: CacheCore,
) -> None:
    namespace = NamespaceId("example", "posts")
    old = core.capture_namespace_generation(namespace, partition=partition_scalar(42))
    core.admit_namespace(old, "obsolete", 1)
    old.release()
    core.record_write(namespace, 1)
    current = core.capture_namespace_generation(
        namespace, partition=partition_scalar(42)
    )
    core.admit_namespace(current, "current", 2)
    current.release()
    ordinary = core.capture_namespace_generation(namespace)
    core.admit_namespace(ordinary, "obsolete", 3)
    captures = [
        core.capture_namespace_generation(
            namespace, partition=partition_scalar(partition)
        )
        for partition in range(100, 1123)
    ]
    fallback = core.capture_namespace_generation(
        namespace, partition=partition_scalar(9999)
    )
    core.record_write(namespace, 1, partition=partition_scalar(9998))
    assert (
        core.admit_namespace(fallback, "fallback", 4) is AdmissionOutcome.DECLINED_STALE
    )
    assert core.lookup_namespace(namespace, "current").value == 2
    ordinary = core.capture_namespace_generation(namespace)
    core.admit_namespace(ordinary, "current", 5)
    replacement = core.capture_namespace_generation(
        namespace, partition=partition_scalar(9999)
    )
    core.record_write(namespace, 1, partition=partition_scalar(9998))
    assert (
        core.admit_namespace(replacement, "replacement", 6) is AdmissionOutcome.ADMITTED
    )
    assert len(captures) == 1023


class SelectiveAdmissionMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.resource = configured_core()
        self.core = self.resource.__enter__()
        self.namespace = NamespaceId("example", "posts")
        self.fence = 0
        self.versions = [0] * 8
        self.captures: list[
            tuple[
                NamespaceCaptureView,
                NonNegativeInt,
                NonNegativeInt,
                NonNegativeInt,
                bool,
            ]
        ] = []
        self.residents: dict[
            tuple[NonNegativeInt, NonNegativeInt], tuple[NonNegativeInt, NonNegativeInt]
        ] = {}

    @rule(partition=st.integers(min_value=0, max_value=7))
    def capture(self, partition: NonNegativeInt) -> None:
        capture = self.core.capture_namespace_generation(
            self.namespace,
            partition=partition_scalar(partition),
            dependencies=("author_id",),
        )
        self.captures.append(
            (capture, partition, self.versions[partition], self.fence, False)
        )

    @rule(partition=st.integers(min_value=0, max_value=7))
    def insert(self, partition: NonNegativeInt) -> None:
        self.core.record_write(
            self.namespace, partition, partition=partition_scalar(partition)
        )
        self.versions[partition] += 1

    @rule(relevant=st.booleans())
    def update(self, relevant: bool) -> None:
        self.core.record_write(
            self.namespace, 0, changed_paths=["author_id" if relevant else "views"]
        )
        if relevant:
            self.versions = [version + 1 for version in self.versions]

    @rule(
        transition=st.sampled_from(
            ("drop_namespace", "clear_namespace", "record_index_change")
        )
    )
    def transition(self, transition: str) -> None:
        getattr(self.core, transition)(self.namespace)
        self.fence += 1

    @precondition(lambda self: bool(self.captures))
    @rule(index=st.integers(min_value=0, max_value=100))
    def admit(self, index: NonNegativeInt) -> None:
        index %= len(self.captures)
        capture, partition, version, fence, released = self.captures[index]
        key = (partition, index)
        valid = (
            not released and fence == self.fence and version == self.versions[partition]
        )
        outcome = self.core.admit_namespace(capture, key, partition)
        if valid:
            if key not in self.residents or self.residents[key] != (version, fence):
                assert outcome is AdmissionOutcome.ADMITTED
            assert outcome in {
                AdmissionOutcome.ADMITTED,
                AdmissionOutcome.DECLINED_STALE,
            }
            if outcome is AdmissionOutcome.ADMITTED:
                self.residents[key] = (version, fence)
        else:
            assert outcome is AdmissionOutcome.DECLINED_STALE

    @precondition(lambda self: bool(self.captures))
    @rule(index=st.integers(min_value=0, max_value=100))
    def release(self, index: NonNegativeInt) -> None:
        index %= len(self.captures)
        capture, partition, version, fence, _released = self.captures[index]
        capture.release()
        self.captures[index] = (capture, partition, version, fence, True)

    @invariant()
    def resident_results_obey_mongodb_dependencies(self) -> None:
        for key, (version, fence) in self.residents.items():
            assert self.core.lookup_namespace(self.namespace, key).hit is (
                fence == self.fence and version == self.versions[key[0]]
            )

    def teardown(self) -> None:
        self.resource.__exit__(None, None, None)


def test_selective_admission_operation_ordering() -> None:
    run_state_machine_as_test(SelectiveAdmissionMachine)


class ReentrantKey:
    __slots__ = ("callback", "capture")

    def __init__(
        self,
        callback: Callable[[], object] | None = None,
        capture: NamespaceCaptureView | None = None,
    ) -> None:
        self.callback = callback
        self.capture = capture

    def __hash__(self) -> int:
        return 0

    def __eq__(self, other: object) -> bool:
        callback, self.callback = self.callback, None
        if callback is not None:
            callback()
        return isinstance(other, ReentrantKey)


class FinalizingKey(ReentrantKey):
    __slots__ = ()

    def __del__(self) -> None:
        if self.callback is not None:
            self.callback()


def test_equality_reentry_cannot_publish_an_obsolete_selective_capture(
    core: CacheCore,
) -> None:
    namespace = NamespaceId("example", "posts")
    old = core.capture_namespace_generation(namespace, partition=partition_scalar(42))
    key = ReentrantKey()
    core.admit_namespace(old, key, 1)
    core.record_write(namespace, 1, partition=partition_scalar(99))
    newer = core.capture_namespace_generation(namespace, partition=partition_scalar(42))
    key.callback = lambda: core.admit_namespace(newer, ReentrantKey(), 2)
    assert (
        core.admit_namespace(old, ReentrantKey(), 0) is AdmissionOutcome.DECLINED_STALE
    )
    assert core.lookup_namespace(namespace, ReentrantKey()).value == 2


def test_compatible_source_revalidates_after_equality_reentry(core: CacheCore) -> None:
    namespace = NamespaceId("example", "posts")
    key = ReentrantKey()
    source = PreparedFindRead(canonicalize(("family", key)), 10)
    capture = core.capture_namespace_generation(
        namespace, partition=partition_scalar(42)
    )
    core.admit_namespace(
        capture, source.discriminator, [1, 2], find_source=source.source
    )
    key.callback = lambda: core.record_write(
        namespace, 1, partition=partition_scalar(42)
    )
    narrower = PreparedFindRead(canonicalize(("family", ReentrantKey())), 1)
    assert not core.lookup_find(namespace, narrower).hit


@pytest.mark.parametrize("selective_limit", [2, 3])
def test_mixed_family_sources_keep_a_valid_cover(
    core: CacheCore, selective_limit: PositiveInt
) -> None:
    namespace = NamespaceId("example", "posts")
    family = canonicalize("mixed-admission")
    selective = core.capture_namespace_generation(
        namespace, partition=partition_scalar(42)
    )
    ordinary = core.capture_namespace_generation(namespace)
    for capture, limit in (
        (selective, selective_limit),
        (ordinary, 5 - selective_limit),
    ):
        source = PreparedFindRead(family, limit)
        core.admit_namespace(
            capture,
            source.discriminator,
            [{"_id": index} for index in range(limit)],
            find_source=source.source,
        )
    probe = PreparedFindRead(family, 1)
    assert core.lookup_find(namespace, probe).value == [{"_id": 0}]
    core.record_write(namespace, 99, partition=partition_scalar(99))
    assert core.lookup_find(namespace, probe).value == [{"_id": 0}]
    core.record_write(namespace, 42, partition=partition_scalar(42))
    assert not core.lookup_find(namespace, probe).hit


def test_key_capture_cycle_can_retire_after_core_close(core: CacheCore) -> None:
    namespace = NamespaceId("example", "posts")
    capture = core.capture_namespace_generation(
        namespace, partition=partition_scalar(42)
    )
    core.admit_namespace(capture, ReentrantKey(capture=capture), 1)
    del capture
    core.close()
    gc.collect()


def test_retired_key_finalizer_can_reenter_the_native_owner(core: CacheCore) -> None:
    namespace = NamespaceId("example", "posts")
    capture = core.capture_namespace_generation(
        namespace, partition=partition_scalar(42)
    )
    finalized = []
    core.admit_namespace(
        capture,
        FinalizingKey(
            lambda: finalized.append(core.try_current_epoch(namespace)), capture
        ),
        1,
    )
    del capture
    core.clear_namespace(namespace)
    assert len(finalized) == 1
    assert finalized[0] is not None


@pytest.mark.parametrize("bounded_core", [1], indirect=True)
def test_eviction_reclaims_only_the_displaced_groups_reservation(
    bounded_core: CacheCore,
) -> None:
    core = bounded_core
    namespace = NamespaceId("example", "posts")
    old = core.capture_namespace_generation(namespace, partition=partition_scalar(42))
    core.admit_namespace(old, "old", 1)
    old.release()
    captures = [
        core.capture_namespace_generation(namespace, partition=partition_scalar(index))
        for index in range(100, 1123)
    ]
    ordinary = core.capture_namespace_generation(
        namespace, partition=partition_scalar(9999)
    )
    core.admit_namespace(ordinary, "evict-old", 1)
    replacement = core.capture_namespace_generation(
        namespace, partition=partition_scalar(10000)
    )
    core.record_write(namespace, 1, partition=partition_scalar(42))
    assert core.admit_namespace(old, "obsolete", 1) is AdmissionOutcome.DECLINED_STALE
    assert core.admit_namespace(replacement, "new", 2) is AdmissionOutcome.ADMITTED
    assert len(captures) == 1023
