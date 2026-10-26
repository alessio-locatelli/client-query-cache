from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, TypedDict

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

from client_query_cache._core.canonical import canonicalize
from client_query_cache._core.codec import encode_value
from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.find_reads import FindReadShape
from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.manager import (
    CacheCore,
    CacheCoreConfig,
    IdentityCapture,
    NamespaceCapture,
)
from client_query_cache._core.order_sensitive_keys import order_sensitive_key
from client_query_cache._shared.shared_index import (
    ArenaPayloads,
    IndexPublisher,
    NamespaceSlot,
)
from client_query_cache._shared.wire import encode_key
from client_query_cache._shared_index import OwnerIndex, ReaderIndex
from client_query_cache._types import NonNegativeInt

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

_DATABASE = "oracle"
_NAMESPACES = (NamespaceId(_DATABASE, "first"), NamespaceId(_DATABASE, "second"))
_IDENTITIES = range(6)
_SHAPES = ("full", "summary")
_EVICTING_BUDGET = CacheCoreConfig(shared_budget_bytes=1_024, max_entry_bytes=512)
_TEXT_CHARACTERS = st.integers(min_value=0, max_value=200)
_EXPIRY_NS = 60 * 10**9
_SLOTS = 64
_ARENA_BYTES = 64 * 1024
_RING_TOKENS = 4_096
_STALE_PROGRESS_NS = 1
_BOUNDED_FIND_SHAPE = FindReadShape(("find", "sorted"), 8)
_FIND_SHAPES = tuple(
    FindReadShape(("find", name), limit) for name in _SHAPES for limit in (0, 1, 3)
)


@pytest.fixture
def bounded_shared_index(
    request: pytest.FixtureRequest,
) -> Iterator[tuple[CacheCore, IndexPublisher, OwnerIndex, ReaderIndex]]:
    index = OwnerIndex(4, 4096, 1, 1, 1, _EXPIRY_NS)
    publisher = IndexPublisher(index, (_DATABASE,), 1)
    core = CacheCore(
        getattr(request, "param", CacheCoreConfig(max_namespaces=1)),
        observer=publisher,
        payloads=ArenaPayloads(index),
    )
    ring = index.session_ring(8)
    descriptor = index.reader_descriptor()
    reader = ReaderIndex(descriptor, ring.descriptor())
    ring.close_descriptor()
    publisher.progress(_DATABASE)
    try:
        yield core, publisher, index, reader
    finally:
        os.close(descriptor)
        core.close()


def test_recycled_namespace_slot_rejects_a_reader_with_the_old_epoch(
    bounded_shared_index: tuple[CacheCore, IndexPublisher, OwnerIndex, ReaderIndex],
) -> None:
    core, publisher, _index, reader = bounded_shared_index
    identity = encode_key(canonicalize(order_sensitive_key(1)))
    shape = encode_key(canonicalize("full"))
    first = NamespaceId(_DATABASE, "first")
    second = NamespaceId(_DATABASE, "second")
    first_epoch = core.current_epoch(first)
    first_slot = publisher.assign(first, first_epoch)
    assert first_slot is not None
    assert (
        core.admit_identity(
            core.begin_identity_admission(first, 1), "full", {"value": "first"}
        )
        is AdmissionOutcome.ADMITTED
    )
    assert (
        reader.lookup(
            first_slot.database, first_slot.namespace, first_epoch, identity, shape
        )
        is not None
    )

    core.drop_namespace(first)
    second_epoch = core.current_epoch(second)
    second_slot = publisher.assign(second, second_epoch)
    assert second_slot == first_slot
    assert second_epoch > first_epoch
    assert (
        core.admit_identity(
            core.begin_identity_admission(second, 1), "full", {"value": "second"}
        )
        is AdmissionOutcome.ADMITTED
    )

    assert (
        reader.lookup(
            second_slot.database, second_slot.namespace, first_epoch, identity, shape
        )
        is None
    )
    assert (
        reader.lookup(
            second_slot.database, second_slot.namespace, second_epoch, identity, shape
        )
        is not None
    )


def test_publisher_returns_no_slot_when_its_capacity_is_full(
    bounded_shared_index: tuple[CacheCore, IndexPublisher, OwnerIndex, ReaderIndex],
) -> None:
    _core, publisher, _index, _reader = bounded_shared_index

    assert publisher.assign(_NAMESPACES[0], 0) == NamespaceSlot(0, 0)
    assert publisher.assign(_NAMESPACES[1], 0) is None


def test_unassigned_namespace_lifecycle_events_do_not_publish_to_the_index(
    bounded_shared_index: tuple[CacheCore, IndexPublisher, OwnerIndex, ReaderIndex],
) -> None:
    core, publisher, _index, _reader = bounded_shared_index
    namespace = NamespaceId(_DATABASE, "unassigned")
    capture = core.begin_identity_admission(namespace, 1)

    assert (
        core.admit_identity(capture, "full", {"value": "unassigned"})
        is AdmissionOutcome.ADMITTED
    )
    core.record_write(namespace, 1)
    core.record_write(namespace, float("nan"))
    core.clear_namespace(namespace)
    core.drop_namespace(namespace)

    assert publisher.assigned(namespace) is None
    assert publisher._published == {}


def test_stale_namespace_release_does_not_remove_a_reused_namespace_slot(
    bounded_shared_index: tuple[CacheCore, IndexPublisher, OwnerIndex, ReaderIndex],
) -> None:
    core, publisher, _index, _reader = bounded_shared_index
    namespace = _NAMESPACES[0]
    first_epoch = core.current_epoch(namespace)
    first_slot = publisher.assign(namespace, first_epoch)
    assert first_slot is not None

    core.drop_namespace(namespace)
    next_epoch = core.current_epoch(namespace)
    next_slot = publisher.assign(namespace, next_epoch)
    assert next_slot == first_slot

    publisher.namespace_released(namespace, first_epoch)

    assert publisher.assigned(namespace) == next_slot


def test_namespace_churn_reuses_owner_state_and_shared_slot(
    bounded_shared_index: tuple[CacheCore, IndexPublisher, OwnerIndex, ReaderIndex],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="client_query_cache._core.manager")
    core, publisher, _index, _reader = bounded_shared_index

    for index in range(1_000):
        namespace = NamespaceId(_DATABASE, f"collection_{index}")
        epoch = core.current_epoch(namespace)
        slot = publisher.assign(namespace, epoch)
        core.record_write(namespace, 0)

        assert slot == NamespaceSlot(0, 0)
        core.drop_namespace(namespace)

    assert len(core._namespaces) == 0
    assert len(core._database_namespaces) == 0
    assert publisher._namespaces == {}
    assert publisher._epochs == {}
    assert publisher._free_slots == [0]


@pytest.mark.parametrize(
    "identity",
    [42, float("nan"), {1, 2}],
    ids=["ordinary", "non-reflexive", "unhashable"],
)
def test_every_write_removes_find_publication_without_removing_other_identities(
    bounded_shared_index: tuple[CacheCore, IndexPublisher, OwnerIndex, ReaderIndex],
    identity: object,
) -> None:
    core, publisher, index, reader = bounded_shared_index
    namespace = NamespaceId("oracle", "first")
    epoch = core.current_epoch(namespace)
    slot = publisher.assign(namespace, epoch)
    assert slot is not None
    core.admit_identity(core.begin_identity_admission(namespace, 1), "full", {"_id": 1})
    for _ in range(2):
        capture = core.capture_namespace_generation(namespace)
        assert (
            core.admit_namespace(
                capture,
                _BOUNDED_FIND_SHAPE.discriminator,
                [],
                find_source=_BOUNDED_FIND_SHAPE.source,
            )
            is AdmissionOutcome.ADMITTED
        )
        assert (
            reader.lookup_find(
                0,
                slot.namespace,
                epoch,
                encode_key(canonicalize(_BOUNDED_FIND_SHAPE.family)),
                _BOUNDED_FIND_SHAPE.limit,
            )
            is not None
        )
        core.record_write(namespace, identity)
        assert (
            reader.lookup_find(
                0,
                slot.namespace,
                epoch,
                encode_key(canonicalize(_BOUNDED_FIND_SHAPE.family)),
                _BOUNDED_FIND_SHAPE.limit,
            )
            is None
        )
        assert (
            reader.lookup(0, slot.namespace, epoch, encode_key(1), encode_key("full"))
            is not None
        )
        assert index.published() == 1
        assert (
            core.admit_namespace(
                capture,
                _BOUNDED_FIND_SHAPE.discriminator,
                [],
                find_source=_BOUNDED_FIND_SHAPE.source,
            )
            is AdmissionOutcome.DECLINED_STALE
        )


class LocalCapture(TypedDict):
    core: NamespaceCapture
    epoch: NonNegativeInt
    token: tuple[NonNegativeInt, NonNegativeInt, NonNegativeInt] | None


class _SharedIndexMachine(RuleBasedStateMachine):
    captures = Bundle("captures")
    local_captures = Bundle("local_captures")

    def __init__(self) -> None:
        super().__init__()
        self.faker = Faker()
        self.index = OwnerIndex(
            _SLOTS, _ARENA_BYTES, 1, len(_NAMESPACES), 1, _EXPIRY_NS
        )
        self.publisher = IndexPublisher(self.index, (_DATABASE,), len(_NAMESPACES))
        self.index.enable_capture(enabled=True)
        self.core = CacheCore(
            _EVICTING_BUDGET,
            observer=self.publisher,
            payloads=ArenaPayloads(self.index),
        )
        ring = self.index.session_ring(_RING_TOKENS)
        descriptor = self.index.reader_descriptor()
        self.reader = ReaderIndex(descriptor, ring.descriptor())
        ring.close_descriptor()
        self.ring = ring
        self.descriptor = descriptor
        self.slots: dict[NamespaceId, NamespaceSlot | None] = {}
        self.epochs: dict[NamespaceId, set[NonNegativeInt]] = {}
        for namespace in _NAMESPACES:
            epoch = self.core.current_epoch(namespace)
            self.slots[namespace] = self.publisher.assign(namespace, epoch)
            self.epochs[namespace] = {epoch}
        self.publisher.progress(_DATABASE)

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
    def capture(self, namespace: NamespaceId, identity: int) -> IdentityCapture:
        return self.core.begin_identity_admission(namespace, identity)

    @rule(target=local_captures, namespace=st.sampled_from(_NAMESPACES))
    def local_capture(self, namespace: NamespaceId) -> LocalCapture:
        slot = self.slots[namespace]
        assert slot is not None
        epoch = self.core.current_epoch(namespace)
        return {
            "core": self.core.capture_namespace_generation(namespace),
            "epoch": epoch,
            "token": self.reader.capture(slot.database, slot.namespace, epoch),
        }

    @rule(capture=consumes(local_captures))
    def validate_local_capture(self, capture: LocalCapture) -> None:
        core_capture = capture["core"]
        slot = self.slots[core_capture.namespace]
        assert slot is not None
        token = capture["token"]
        if token is not None and self.index.validate_capture(
            slot.database,
            slot.namespace,
            capture["epoch"],
            self.reader.incarnation,
            token,
            _EXPIRY_NS,
        ):
            assert self.core.is_database_available(_DATABASE)
            assert (
                self.core.capture_namespace_generation(core_capture.namespace)
                == core_capture
            )

    @rule(
        capture=consumes(captures),
        shape=st.sampled_from(_SHAPES),
        seed=st.integers(),
        characters=_TEXT_CHARACTERS,
    )
    def admit(
        self, capture: IdentityCapture, shape: str, seed: int, characters: int
    ) -> None:
        self.core.admit_identity_encoded(
            capture, shape, self._document(seed, characters)
        )

    @rule(
        namespace=st.sampled_from(_NAMESPACES),
        identity=st.sampled_from(_IDENTITIES),
    )
    def write(self, namespace: NamespaceId, identity: int) -> None:
        self.core.record_write(namespace, identity)

    @rule(namespace=st.sampled_from(_NAMESPACES))
    def reset(self, namespace: NamespaceId) -> None:
        self.core.clear_namespace(namespace)
        self.epochs[namespace].add(self.core.current_epoch(namespace))

    @rule(available=st.booleans())
    def toggle_availability(self, *, available: bool) -> None:
        self.core.set_database_available(_DATABASE, available=available)

    @rule(fresh=st.booleans())
    def progress(self, *, fresh: bool) -> None:
        if fresh:
            self.publisher.progress(_DATABASE)
        else:
            self.index.set_progress(0, _STALE_PROGRESS_NS)

    @rule()
    def drain(self) -> None:
        for token in (
            self.ring.drain()
        ):  # pragma: lax no cover (generated runs may drain only empty rings)
            key = self.publisher.key(token)
            if key is not None:
                self.core._lru.touch(key)

    @invariant()
    def local_values_match_the_core(self) -> None:
        for namespace, slot in self.slots.items():
            assert slot is not None
            for identity in _IDENTITIES:
                canonical = encode_key(canonicalize(order_sensitive_key(identity)))
                for shape in _SHAPES:
                    for epoch in self.epochs[namespace]:
                        local = self.reader.lookup(
                            slot.database,
                            slot.namespace,
                            epoch,
                            canonical,
                            encode_key(canonicalize(shape)),
                        )
                        if local is None:
                            continue
                        assert epoch == self.core.current_epoch(namespace)
                        assert local == self.core.lookup_identity_encoded(
                            namespace, identity, shape
                        )


def test_local_reads_never_disagree_with_the_core() -> None:
    run_state_machine_as_test(_SharedIndexMachine)  # type: ignore[no-untyped-call]


class _SharedFindIndexMachine(_SharedIndexMachine):
    find_captures = Bundle("find_captures")

    @rule(target=find_captures, namespace=st.sampled_from(_NAMESPACES))
    def capture_find(self, namespace: NamespaceId) -> NamespaceCapture:
        return self.core.capture_namespace_generation(namespace)

    @rule(capture=consumes(find_captures), shape=st.sampled_from(_FIND_SHAPES))
    def admit_find(self, capture: NamespaceCapture, shape: FindReadShape) -> None:
        self.core.admit_namespace(
            capture,
            shape.discriminator,
            [{"name": self.faker.name()}],
            find_source=shape.source,
        )

    @invariant()
    def local_find_values_match_the_core(self) -> None:
        for namespace, slot in self.slots.items():
            assert slot is not None
            for find_shape in _FIND_SHAPES:
                for epoch in self.epochs[namespace]:
                    local = self.reader.lookup_find(
                        slot.database,
                        slot.namespace,
                        epoch,
                        encode_key(canonicalize(find_shape.family)),
                        find_shape.limit,
                    )
                    if isinstance(local, bytes):
                        assert local == self.core.lookup_find_encoded(
                            namespace, find_shape
                        )
                    elif isinstance(local, tuple):
                        assert (
                            self.core.lookup_find_encoded(namespace, find_shape) is None
                        )


def test_local_find_reads_never_disagree_with_the_core() -> None:
    run_state_machine_as_test(_SharedFindIndexMachine)  # type: ignore[no-untyped-call]


@pytest.mark.parametrize("payload_characters", [0, 2048], ids=["slots", "arena"])
def test_incomplete_find_publication_retains_owner_reuse_and_reclaims_state(
    bounded_shared_index: tuple[CacheCore, IndexPublisher, OwnerIndex, ReaderIndex],
    payload_characters: NonNegativeInt,
) -> None:
    core, publisher, index, reader = bounded_shared_index
    index.enable_capture(enabled=True)
    namespace = _NAMESPACES[0]
    slot = publisher.assign(namespace, core.current_epoch(namespace))
    assert slot is not None
    for ordinal in range(8):
        shape = FindReadShape(("find", ordinal), 8)
        assert (
            core.admit_namespace(
                core.capture_namespace_generation(namespace),
                shape.discriminator,
                [{"payload": "x" * payload_characters}],
                find_source=shape.source,
            )
            is AdmissionOutcome.ADMITTED
        )
    assert publisher._unpublished_finds[namespace]
    assert len(publisher._unpublished_finds[namespace]) <= core.snapshot().entry_count
    assert core.lookup_find_encoded(namespace, shape) is not None
    assert (
        reader.lookup_find(
            slot.database,
            slot.namespace,
            core.current_epoch(namespace),
            encode_key(canonicalize(shape.family)),
            4,
        )
        is None
    )
    core.clear_namespace(namespace)
    assert publisher._unpublished_finds == {}
    assert index.published() == 0
    assert isinstance(
        reader.lookup_find(
            slot.database,
            slot.namespace,
            core.current_epoch(namespace),
            encode_key("absent"),
            4,
        ),
        tuple,
    )
    core.drop_namespace(namespace)
    assert publisher._finds == {}
    assert publisher._unpublished_finds == {}


def test_unassigned_find_state_does_not_survive_a_write(
    bounded_shared_index: tuple[CacheCore, IndexPublisher, OwnerIndex, ReaderIndex],
) -> None:
    core, publisher, index, reader = bounded_shared_index
    index.enable_capture(enabled=True)
    namespace = _NAMESPACES[0]
    shape = _BOUNDED_FIND_SHAPE
    assert (
        core.admit_namespace(
            core.capture_namespace_generation(namespace),
            shape.discriminator,
            [],
            find_source=shape.source,
        )
        is AdmissionOutcome.ADMITTED
    )
    assert publisher._unpublished_finds[namespace]
    core.record_write(namespace, 0)
    assert publisher._unpublished_finds == {}
    epoch = core.current_epoch(namespace)
    slot = publisher.assign(namespace, epoch)
    assert slot is not None
    assert isinstance(
        reader.lookup_find(
            slot.database,
            slot.namespace,
            epoch,
            encode_key(canonicalize(shape.family)),
            4,
        ),
        tuple,
    )


@pytest.mark.parametrize("bounded_shared_index", [_EVICTING_BUDGET], indirect=True)
def test_eviction_removes_individual_unpublished_find_references(
    bounded_shared_index: tuple[CacheCore, IndexPublisher, OwnerIndex, ReaderIndex],
) -> None:
    core, publisher, index, reader = bounded_shared_index
    index.enable_capture(enabled=True)
    namespace = _NAMESPACES[0]
    epoch = core.current_epoch(namespace)
    slot = publisher.assign(namespace, epoch)
    assert slot is not None
    for ordinal in range(6):
        shape = FindReadShape(("find", ordinal), 8)
        assert (
            core.admit_namespace(
                core.capture_namespace_generation(namespace),
                shape.discriminator,
                [{"payload": "small"}],
                find_source=shape.source,
            )
            is AdmissionOutcome.ADMITTED
        )
    assert len(publisher._unpublished_finds[namespace]) > 1
    for ordinal in range(4):
        assert (
            core.admit_identity(
                core.begin_identity_admission(namespace, ordinal),
                "full",
                {"payload": "x" * 350},
            )
            is AdmissionOutcome.ADMITTED
        )
    assert publisher._unpublished_finds == {}
    assert isinstance(
        reader.lookup_find(
            slot.database,
            slot.namespace,
            epoch,
            encode_key("absent"),
            4,
        ),
        tuple,
    )


@given(
    lengths=st.lists(st.integers(min_value=0, max_value=3000), min_size=1, max_size=50)
)
def test_released_arena_capacity_supports_changing_payload_sizes(
    lengths: list[NonNegativeInt],
) -> None:
    index = OwnerIndex(8, 4096, 1, 1, 1, _EXPIRY_NS)
    for length in lengths:
        encoded = bytes(length)
        payload = index.store(encoded)
        assert payload is not None
        assert index.snapshot(payload) == encoded
        index.release(payload)
        assert index.snapshot(payload) is None
