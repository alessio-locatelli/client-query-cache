from __future__ import annotations

import os
from typing import TypedDict

import pytest
from client_query_cache_shared_index import OwnerIndex, ReaderIndex
from faker import Faker
from hypothesis import strategies as st
from hypothesis.stateful import (
    Bundle,
    RuleBasedStateMachine,
    consumes,
    invariant,
    rule,
    run_state_machine_as_test,
)

from benchmarks.stream_cost.shared_cache.shared_index import (
    ArenaPayloads,
    IndexPublisher,
)
from benchmarks.stream_cost.shared_cache.wire import encode_key
from client_query_cache._core.canonical import canonicalize
from client_query_cache._core.codec import encode_value
from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.manager import (
    CacheCore,
    CacheCoreConfig,
    IdentityCapture,
    NamespaceCapture,
)
from client_query_cache._core.order_sensitive_keys import order_sensitive_key
from client_query_cache._types import NonNegativeInt

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
        self.slots = {
            namespace: self.publisher.assign(namespace, 0) for namespace in _NAMESPACES
        }
        self.epochs: dict[NamespaceId, set[int]] = {
            namespace: {0} for namespace in _NAMESPACES
        }
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
