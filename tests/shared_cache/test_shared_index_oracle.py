from __future__ import annotations

import os
import time
from contextlib import closing
from typing import TYPE_CHECKING, NamedTuple, TypedDict

import pytest
from faker import Faker
from hypothesis import given
from hypothesis import strategies as st
from hypothesis.stateful import (
    Bundle,
    RuleBasedStateMachine,
    consumes,
    invariant,
    rule,
    run_state_machine_as_test,
)

from client_query_cache import CacheCoreConfig
from client_query_cache._core.codec import encode_value
from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.find_reads import FindReadShape
from client_query_cache._core.keys import NamespaceId
from client_query_cache._shared_index import OwnerIndex, ReaderIndex, SharedOwnerCore
from client_query_cache._types import NonNegativeInt, PositiveInt
from tests.epoch_helpers import current_epoch
from tests.shared_cache.conftest import Racing
from tests.shared_cache.index_helpers import assign_slot, identity_key, shape_key

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from client_query_cache._shared_index import LocalCapture, SessionRing

pytestmark = pytest.mark.unit

_DATABASE = "oracle"
_NAMESPACES = (NamespaceId(_DATABASE, "first"), NamespaceId(_DATABASE, "second"))
_IDENTITIES = range(6)
_SHAPES = ("full", "summary")
_EVICTING_BUDGET = CacheCoreConfig(budget_bytes=1_024, max_entry_bytes=512)
_TEXT_CHARACTERS = st.integers(min_value=0, max_value=200)
_EXPIRY_NS = 60 * 10**9
_PROBE_TTL_SECONDS = 30.0
_SLOTS = 64
_ARENA_BYTES = 64 * 1024
_SINGLE_PUBLICATION_ARENA = 176
_RING_TOKENS = 4_096
_STALE_PROGRESS_NS = 1
_BOUNDED_FIND_SHAPE = FindReadShape(("find", "sorted"), 8)
_FIND_SHAPES = tuple(
    FindReadShape(("find", name), limit) for name in _SHAPES for limit in (1, 3)
)
_SHAPE = "full"


def _admit(
    core: SharedOwnerCore,
    namespace: NamespaceId,
    identity: object,
    value: object,
    shape: object = _SHAPE,
) -> AdmissionOutcome:
    return core.admit_identity_published(
        core.begin_identity_admission(namespace, identity),
        shape,
        encode_value(value),
        identity_key(identity),
        shape_key(_SHAPE),
    )


def _admit_find(
    core: SharedOwnerCore,
    capture: LocalCapture,
    shape: FindReadShape,
    value: object,
) -> AdmissionOutcome:
    return core.admit_namespace_published(
        capture,
        shape.discriminator,
        encode_value(value),
        shape_key(shape.discriminator),
        find_source=shape.source,
    )


def _shared_core(
    index: OwnerIndex, config: CacheCoreConfig, namespaces: PositiveInt
) -> SharedOwnerCore:
    return SharedOwnerCore(config, index, [_DATABASE], namespaces, _PROBE_TTL_SECONDS)


class _SharedIndex(NamedTuple):
    core: SharedOwnerCore
    owner_index: OwnerIndex
    ring: SessionRing
    reader: ReaderIndex


@pytest.fixture
def make_shared_index() -> Iterator[Callable[..., _SharedIndex]]:
    opened: list[tuple[int, SharedOwnerCore]] = []

    def create(
        slots: PositiveInt = 8,
        arena_bytes: PositiveInt = 4096,
        ring_tokens: PositiveInt = 8,
        config: CacheCoreConfig | None = None,
    ) -> _SharedIndex:
        index = OwnerIndex(slots, arena_bytes, 1, 1, 1, _EXPIRY_NS)
        core = _shared_core(index, config or CacheCoreConfig(max_namespaces=1), 1)
        ring = index.session_ring(ring_tokens)
        descriptor = index.reader_descriptor()
        reader = ReaderIndex(descriptor, ring.descriptor())
        ring.close_descriptor()
        index.set_progress(0, time.monotonic_ns())
        opened.append((descriptor, core))
        return _SharedIndex(core, index, ring, reader)

    yield create
    for descriptor, core in opened:
        os.close(descriptor)
        core.close()


@pytest.fixture
def bounded_shared_index(
    make_shared_index: Callable[..., _SharedIndex],
) -> tuple[SharedOwnerCore, OwnerIndex, ReaderIndex]:
    core, index, _ring, reader = make_shared_index()
    return core, index, reader


def test_recycled_namespace_slot_rejects_a_reader_with_the_old_epoch(
    bounded_shared_index: tuple[SharedOwnerCore, OwnerIndex, ReaderIndex],
) -> None:
    core, _index, reader = bounded_shared_index
    identity = identity_key(1)
    shape = shape_key(_SHAPE)
    first = NamespaceId(_DATABASE, "first")
    second = NamespaceId(_DATABASE, "second")
    first_slot = assign_slot(core, first)
    first_epoch = current_epoch(core, first)
    assert first_slot is not None
    assert _admit(core, first, 1, {"value": "first"}) is AdmissionOutcome.ADMITTED
    assert reader.lookup(*first_slot, first_epoch, identity, shape) is not None

    core.drop_namespace(first)
    second_slot = assign_slot(core, second)
    second_epoch = current_epoch(core, second)
    assert second_slot == first_slot
    assert second_epoch > first_epoch
    assert _admit(core, second, 1, {"value": "second"}) is AdmissionOutcome.ADMITTED

    assert reader.lookup(*second_slot, first_epoch, identity, shape) is None
    assert reader.lookup(*second_slot, second_epoch, identity, shape) is not None


def test_a_namespace_beyond_the_slot_capacity_receives_no_slot(
    bounded_shared_index: tuple[SharedOwnerCore, OwnerIndex, ReaderIndex],
) -> None:
    core, _index, _reader = bounded_shared_index

    assert assign_slot(core, _NAMESPACES[0]) == (0, 0)
    assert assign_slot(core, _NAMESPACES[1]) is None
    assert core.assigned_slot(_NAMESPACES[1]) is None


def test_unassigned_namespace_lifecycle_events_do_not_publish_to_the_index(
    bounded_shared_index: tuple[SharedOwnerCore, OwnerIndex, ReaderIndex],
) -> None:
    core, index, _reader = bounded_shared_index
    namespace = NamespaceId(_DATABASE, "unassigned")

    assert _admit(core, namespace, 1, {"value": "unassigned"}) is (
        AdmissionOutcome.ADMITTED
    )
    core.record_write(namespace, 1)
    core.record_write(namespace, float("nan"))
    core.clear_namespace(namespace)
    core.drop_namespace(namespace)

    assert core.assigned_slot(namespace) is None
    assert index.published() == 0


def test_stale_namespace_release_does_not_remove_a_reused_namespace_slot(
    bounded_shared_index: tuple[SharedOwnerCore, OwnerIndex, ReaderIndex],
) -> None:
    core, _index, _reader = bounded_shared_index
    namespace = _NAMESPACES[0]
    first_slot = assign_slot(core, namespace)
    first_epoch = current_epoch(core, namespace)
    assert first_slot is not None

    core.drop_namespace(namespace)
    next_slot = assign_slot(core, namespace)
    assert next_slot == first_slot

    assert not core.release_namespace_if_epoch_matches(namespace, first_epoch)
    assert core.assigned_slot(namespace) == next_slot


def test_namespace_churn_reuses_owner_state_and_shared_slot(
    bounded_shared_index: tuple[SharedOwnerCore, OwnerIndex, ReaderIndex],
) -> None:
    core, _index, _reader = bounded_shared_index

    for index in range(1_000):
        namespace = NamespaceId(_DATABASE, f"collection_{index}")
        slot = assign_slot(core, namespace)
        core.record_write(namespace, 0)

        assert slot == (0, 0)
        core.drop_namespace(namespace)
        assert core.assigned_slot(namespace) is None

    assert core.namespaces_for_database(_DATABASE) == []


@pytest.mark.parametrize(
    "identity",
    [42, float("nan"), {1, 2}],
    ids=["ordinary", "non-reflexive", "unhashable"],
)
def test_every_write_removes_find_publication_without_removing_other_identities(
    bounded_shared_index: tuple[SharedOwnerCore, OwnerIndex, ReaderIndex],
    identity: object,
) -> None:
    core, index, reader = bounded_shared_index
    namespace = NamespaceId("oracle", "first")
    slot = assign_slot(core, namespace)
    epoch = current_epoch(core, namespace)
    assert slot is not None
    _admit(core, namespace, 1, {"_id": 1})
    find_key = shape_key(_BOUNDED_FIND_SHAPE.discriminator)
    for _ in range(2):
        capture = core.capture_namespace_generation(namespace)
        assert (
            _admit_find(core, capture, _BOUNDED_FIND_SHAPE, [])
            is AdmissionOutcome.ADMITTED
        )
        assert reader.lookup(*slot, epoch, b"", find_key) is not None
        core.record_write(namespace, identity)
        assert reader.lookup(*slot, epoch, b"", find_key) is None
        assert (
            reader.lookup(*slot, epoch, identity_key(1), shape_key(_SHAPE)) is not None
        )
        assert index.published() == 1
        assert (
            _admit_find(core, capture, _BOUNDED_FIND_SHAPE, [])
            is AdmissionOutcome.DECLINED_STALE
        )


@pytest.mark.parametrize("race", ["write", "unavailable", "reset"])
def test_a_mutation_during_admission_prevents_its_publication(
    bounded_shared_index: tuple[SharedOwnerCore, OwnerIndex, ReaderIndex],
    race: str,
) -> None:
    core, index, _reader = bounded_shared_index
    namespace = _NAMESPACES[0]
    assign_slot(core, namespace)
    actions: dict[str, Callable[[], object]] = {
        "write": lambda: core.record_write(namespace, 1),
        "unavailable": lambda: core.set_database_available(_DATABASE, available=False),
        "reset": lambda: core.clear_namespace(namespace),
    }

    outcome = _admit(core, namespace, 1, {"value": 1}, Racing(_SHAPE, actions[race]))

    assert outcome is not AdmissionOutcome.ADMITTED
    assert index.published() == 0
    assert not core.lookup_identity(namespace, 1, _SHAPE).hit


def test_a_full_arena_keeps_owner_served_bytes_without_publication(
    make_shared_index: Callable[..., _SharedIndex],
) -> None:
    shared = make_shared_index(arena_bytes=64)
    core = shared.core
    assign_slot(core, _NAMESPACES[0])
    value = {"text": "x" * 128}

    assert _admit(core, _NAMESPACES[0], 1, value) is AdmissionOutcome.ADMITTED
    assert shared.owner_index.published() == 0
    assert core.lookup_identity_encoded(_NAMESPACES[0], 1, _SHAPE) == (
        encode_value(value)
    )


def test_a_replacement_in_a_full_arena_is_published_in_the_block_it_frees(
    make_shared_index: Callable[..., _SharedIndex], faker: Faker
) -> None:
    core, index, _ring, reader = make_shared_index(
        arena_bytes=_SINGLE_PUBLICATION_ARENA
    )
    namespace = _NAMESPACES[0]
    slot = assign_slot(core, namespace)
    assert slot is not None
    epoch = current_epoch(core, namespace)
    for revision in range(2):
        core.record_write(namespace, revision)
        value = {"text": faker.pystr(min_chars=80, max_chars=80)}

        assert _admit(core, namespace, 1, value) is AdmissionOutcome.ADMITTED
        assert index.published() == 1
        assert reader.lookup(
            *slot, epoch, identity_key(1), shape_key(_SHAPE)
        ) == encode_value(value)


_ENTRY_VALUES = {number: {"value": f"v{number}"} for number in range(1, 6)}
_ENTRY_BYTES = len(encode_value(_ENTRY_VALUES[1]))
_THREE_ENTRIES = CacheCoreConfig(
    budget_bytes=3 * _ENTRY_BYTES, max_entry_bytes=_ENTRY_BYTES, max_namespaces=1
)


def _resident(core: SharedOwnerCore, identities: range) -> tuple[bool, ...]:
    return tuple(
        core.lookup_identity_encoded(_NAMESPACES[0], identity, _SHAPE) is not None
        for identity in identities
    )


def test_a_touch_token_of_a_reclaimed_entry_does_not_touch_its_replacement(
    make_shared_index: Callable[..., _SharedIndex],
) -> None:
    core, _index, ring, reader = make_shared_index(
        _SLOTS, _ARENA_BYTES, _RING_TOKENS, _THREE_ENTRIES
    )
    namespace = _NAMESPACES[0]
    slot = assign_slot(core, namespace)
    assert slot is not None
    epoch = current_epoch(core, namespace)
    _admit(core, namespace, 1, _ENTRY_VALUES[1])
    assert reader.lookup(*slot, epoch, identity_key(1), shape_key(_SHAPE))
    core.record_write(namespace, 1)
    _admit(core, namespace, 2, _ENTRY_VALUES[2])
    assert _admit(core, namespace, 1, _ENTRY_VALUES[1]) is AdmissionOutcome.ADMITTED
    _admit(core, namespace, 3, _ENTRY_VALUES[3])

    core.touch(ring)
    _admit(core, namespace, 4, _ENTRY_VALUES[4])
    _admit(core, namespace, 5, _ENTRY_VALUES[5])

    assert _resident(core, range(1, 6)) == (False, False, True, True, True)


def test_a_drained_touch_token_protects_its_entry_from_eviction(
    make_shared_index: Callable[..., _SharedIndex],
) -> None:
    core, _index, ring, reader = make_shared_index(
        _SLOTS, _ARENA_BYTES, _RING_TOKENS, _THREE_ENTRIES
    )
    namespace = _NAMESPACES[0]
    slot = assign_slot(core, namespace)
    assert slot is not None
    epoch = current_epoch(core, namespace)
    for number in (1, 2, 3):
        _admit(core, namespace, number, _ENTRY_VALUES[number])
    assert reader.lookup(*slot, epoch, identity_key(2), shape_key(_SHAPE))

    core.touch(ring)
    _admit(core, namespace, 4, _ENTRY_VALUES[4])
    _admit(core, namespace, 5, _ENTRY_VALUES[5])

    assert _resident(core, range(1, 6)) == (False, True, False, True, True)


def test_close_withdraws_every_publication(
    bounded_shared_index: tuple[SharedOwnerCore, OwnerIndex, ReaderIndex],
) -> None:
    core, index, reader = bounded_shared_index
    slot = assign_slot(core, _NAMESPACES[0])
    assert slot is not None
    epoch = current_epoch(core, _NAMESPACES[0])
    capture = core.begin_identity_admission(_NAMESPACES[0], 2)
    _admit(core, _NAMESPACES[0], 1, {"value": 1})

    core.close()

    assert index.published() == 0
    assert reader.lookup(*slot, epoch, identity_key(1), shape_key(_SHAPE)) is None
    capture.release()


class LocalCaptureState(TypedDict):
    namespace: NamespaceId
    epoch: NonNegativeInt
    token: tuple[NonNegativeInt, NonNegativeInt, NonNegativeInt] | None
    version: NonNegativeInt


class _SharedIndexMachine(RuleBasedStateMachine):
    captures = Bundle("captures")
    local_captures = Bundle("local_captures")

    def __init__(self) -> None:
        super().__init__()
        self.faker = Faker()
        self.index = OwnerIndex(
            _SLOTS, _ARENA_BYTES, 1, len(_NAMESPACES), 1, _EXPIRY_NS
        )
        self.index.enable_capture(enabled=True)
        self.core = _shared_core(self.index, _EVICTING_BUDGET, len(_NAMESPACES))
        ring = self.index.session_ring(_RING_TOKENS)
        descriptor = self.index.reader_descriptor()
        self.reader = ReaderIndex(descriptor, ring.descriptor())
        ring.close_descriptor()
        self.ring = ring
        self.descriptor = descriptor
        self.versions = dict.fromkeys(_NAMESPACES, 0)
        self.slots: dict[NamespaceId, tuple[NonNegativeInt, NonNegativeInt]] = {}
        self.epochs: dict[NamespaceId, set[NonNegativeInt]] = {}
        for namespace in _NAMESPACES:
            slot = assign_slot(self.core, namespace)
            assert slot is not None
            self.slots[namespace] = slot
            self.epochs[namespace] = {current_epoch(self.core, namespace)}
        self.index.set_progress(0, time.monotonic_ns())

    def teardown(self) -> None:
        os.close(self.descriptor)
        self.core.close()

    def _document(self, seed: int, characters: int) -> bytes:
        self.faker.seed_instance(seed)
        text = self.faker.pystr(min_chars=characters, max_chars=characters)
        return encode_value({"name": self.faker.name(), "text": text})

    @rule(
        target=captures,
        namespace=st.sampled_from(_NAMESPACES),
        identity=st.sampled_from(_IDENTITIES),
    )
    def capture(
        self, namespace: NamespaceId, identity: int
    ) -> tuple[LocalCapture, int]:
        return self.core.begin_identity_admission(namespace, identity), identity

    @rule(target=local_captures, namespace=st.sampled_from(_NAMESPACES))
    def local_capture(self, namespace: NamespaceId) -> LocalCaptureState:
        epoch = current_epoch(self.core, namespace)
        return {
            "namespace": namespace,
            "epoch": epoch,
            "token": self.reader.capture(*self.slots[namespace], epoch),
            "version": self.versions[namespace],
        }

    @rule(capture=consumes(local_captures), seed=st.integers())
    def admit_local(self, capture: LocalCaptureState, seed: int) -> None:
        token = capture["token"]
        if token is None:
            return
        namespace = capture["namespace"]
        outcome = self.core.admit_local(
            namespace,
            self.slots[namespace],
            capture["epoch"],
            self.reader.incarnation,
            token,
            _IDENTITIES[0],
            _SHAPES[0],
            self._document(seed, 1),
            identity_key(_IDENTITIES[0]),
            shape_key(_SHAPES[0]),
            _EXPIRY_NS,
        )
        if outcome is AdmissionOutcome.ADMITTED:
            assert capture["version"] == self.versions[namespace]

    @rule(
        capture=consumes(captures),
        shape=st.sampled_from(_SHAPES),
        seed=st.integers(),
        characters=_TEXT_CHARACTERS,
    )
    def admit(
        self,
        capture: tuple[LocalCapture, int],
        shape: str,
        seed: int,
        characters: int,
    ) -> None:
        local_capture, identity = capture
        self.core.admit_identity_published(
            local_capture,
            shape,
            self._document(seed, characters),
            identity_key(identity),
            shape_key(shape),
        )

    @rule(
        namespace=st.sampled_from(_NAMESPACES),
        identity=st.sampled_from(_IDENTITIES),
    )
    def write(self, namespace: NamespaceId, identity: int) -> None:
        self.core.record_write(namespace, identity)
        self.versions[namespace] += 1

    @rule(namespace=st.sampled_from(_NAMESPACES))
    def reset(self, namespace: NamespaceId) -> None:
        self.core.clear_namespace(namespace)
        self.versions[namespace] += 1
        self.epochs[namespace].add(current_epoch(self.core, namespace))

    @rule(available=st.booleans())
    def toggle_availability(self, *, available: bool) -> None:
        changed = self.core.is_database_available(_DATABASE) is not available
        self.core.set_database_available(_DATABASE, available=available)
        if changed:
            for namespace in _NAMESPACES:
                self.versions[namespace] += 1

    @rule(fresh=st.booleans())
    def progress(self, *, fresh: bool) -> None:
        self.index.set_progress(0, time.monotonic_ns() if fresh else _STALE_PROGRESS_NS)

    @rule()
    def drain(self) -> None:
        self.core.touch(self.ring)

    @invariant()
    def local_values_match_the_core(self) -> None:
        for namespace, slot in self.slots.items():
            for identity in _IDENTITIES:
                for shape in _SHAPES:
                    for epoch in self.epochs[namespace]:
                        local = self.reader.lookup(
                            *slot, epoch, identity_key(identity), shape_key(shape)
                        )
                        if local is None:
                            continue
                        assert epoch == current_epoch(self.core, namespace)
                        assert local == self.core.lookup_identity_encoded(
                            namespace, identity, shape
                        )


def test_local_reads_never_disagree_with_the_core() -> None:
    run_state_machine_as_test(_SharedIndexMachine)


class _SharedFindIndexMachine(_SharedIndexMachine):
    find_captures = Bundle("find_captures")

    @rule(target=find_captures, namespace=st.sampled_from(_NAMESPACES))
    def capture_find(self, namespace: NamespaceId) -> LocalCapture:
        return self.core.capture_namespace_generation(namespace)

    @rule(capture=consumes(find_captures), shape=st.sampled_from(_FIND_SHAPES))
    def admit_find(self, capture: LocalCapture, shape: FindReadShape) -> None:
        _admit_find(self.core, capture, shape, [{"name": self.faker.name()}])

    @invariant()
    def local_find_values_match_the_core(self) -> None:
        for namespace, slot in self.slots.items():
            for find_shape in _FIND_SHAPES:
                for epoch in self.epochs[namespace]:
                    local = self.reader.lookup(
                        *slot, epoch, b"", shape_key(find_shape.discriminator)
                    )
                    if (
                        local is not None
                    ):  # pragma: lax no cover (examples may publish no find value)
                        assert local == self.core.lookup_find_encoded(
                            namespace, find_shape
                        )


def test_local_find_reads_never_disagree_with_the_core() -> None:
    run_state_machine_as_test(_SharedFindIndexMachine)


@given(
    lengths=st.lists(st.integers(min_value=0, max_value=3000), min_size=1, max_size=50)
)
def test_released_arena_capacity_supports_changing_payload_sizes(
    lengths: list[NonNegativeInt],
) -> None:
    index = OwnerIndex(8, 4096, 1, 1, 1, _EXPIRY_NS)
    core = _shared_core(index, CacheCoreConfig(max_namespaces=1), 1)
    with closing(core):
        assert assign_slot(core, _NAMESPACES[0]) is not None
        for length in lengths:
            capture = core.begin_identity_admission(_NAMESPACES[0], 1)
            outcome = core.admit_identity_published(
                capture, _SHAPE, bytes(length), identity_key(1), shape_key(_SHAPE)
            )
            assert outcome is AdmissionOutcome.ADMITTED
            assert index.published() == 1
            core.record_write(_NAMESPACES[0], 1)
            assert index.published() == 0
