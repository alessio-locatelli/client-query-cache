from __future__ import annotations

import pytest
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    invariant,
    rule,
    run_state_machine_as_test,
)

from client_query_cache._core.entries import CacheEntry
from client_query_cache._core.keys import NamespaceCacheKey, NamespaceId
from client_query_cache._core.locking import LockOrderGuard
from client_query_cache._core.lru import WeightedLru
from client_query_cache._types import NonNegativeInt

pytestmark = pytest.mark.unit

NAMESPACE = NamespaceId("db", "coll")
SHARED_BUDGET_BYTES = 1_000
ENTRY_COUNT = 100


def make_entry(
    generation_key: tuple[NonNegativeInt, ...], weight: NonNegativeInt = 10
) -> CacheEntry:
    return CacheEntry(
        generation_key=generation_key,
        weight=weight,
        value=b"x" * weight,
        namespace=NAMESPACE,
        identity=None,
    )


def make_key(discriminator: object) -> NamespaceCacheKey:
    return NamespaceCacheKey(namespace=NAMESPACE, discriminator=discriminator)


@pytest.fixture
def lru() -> WeightedLru:
    return WeightedLru(
        shared_budget_bytes=SHARED_BUDGET_BYTES,
        max_entry_bytes=100,
        guard=LockOrderGuard(),
    )


def test_conditional_put_admits_into_empty_key(lru: WeightedLru) -> None:
    admitted, displaced, evicted = lru.conditional_put(make_key("k"), make_entry((1,)))
    assert admitted
    assert displaced is None
    assert evicted == []


@pytest.mark.parametrize(
    ("first_generation_key", "second_generation_key", "second_should_replace"),
    [
        pytest.param((5,), (3,), False, id="older_generation_is_rejected"),
        pytest.param((1,), (2,), True, id="newer_generation_replaces"),
        pytest.param(
            (0, 100),
            (1, 1),
            True,
            id="newer_epoch_outranks_a_larger_identity_generation",
        ),
    ],
)
def test_conditional_put_generation_ordering(
    lru: WeightedLru,
    first_generation_key: tuple[NonNegativeInt, ...],
    second_generation_key: tuple[NonNegativeInt, ...],
    second_should_replace: bool,
) -> None:
    key = make_key("k")
    first = make_entry(first_generation_key)
    lru.conditional_put(key, first)

    second = make_entry(second_generation_key)
    admitted, displaced, _evicted = lru.conditional_put(key, second)

    assert admitted is second_should_replace
    if second_should_replace:
        assert displaced is first
        assert lru.peek(key) is second
    else:
        assert displaced is None
        assert lru.peek(key) is first


def test_eviction_reclaims_least_recently_used_entries(lru: WeightedLru) -> None:
    for index in range(ENTRY_COUNT):
        lru.conditional_put(make_key(index), make_entry((1,), weight=10))

    used_bytes, entry_count = lru.snapshot_usage()
    assert used_bytes <= SHARED_BUDGET_BYTES
    assert entry_count <= ENTRY_COUNT


def test_touching_an_entry_protects_it_from_eviction(lru: WeightedLru) -> None:
    protected_key = make_key("protected")
    lru.conditional_put(protected_key, make_entry((1,), weight=10))

    for index in range(200):
        lru.touch(protected_key)
        lru.conditional_put(make_key(index), make_entry((1,), weight=10))

    assert lru.peek(protected_key) is not None


def test_touching_a_key_no_longer_resident_is_a_no_op(lru: WeightedLru) -> None:
    lru.touch(make_key("never-admitted"))
    assert lru.peek(make_key("never-admitted")) is None


@pytest.mark.parametrize(
    ("weight", "expected_oversize"),
    [
        pytest.param(101, True, id="over_the_max"),
        pytest.param(100, False, id="at_the_max"),
    ],
)
def test_is_oversize(
    lru: WeightedLru,
    weight: NonNegativeInt,
    expected_oversize: bool,
) -> None:
    assert lru.is_oversize(weight) is expected_oversize


def test_peek_does_not_protect_an_entry_from_eviction(lru: WeightedLru) -> None:
    peeked_key = make_key("peeked")
    lru.conditional_put(peeked_key, make_entry((1,), weight=10))

    for index in range(200):
        lru.peek(peeked_key)
        lru.conditional_put(make_key(index), make_entry((1,), weight=10))

    assert lru.peek(peeked_key) is None


def test_remove_exact_only_removes_the_matching_token(lru: WeightedLru) -> None:
    key = make_key("k")
    stale = make_entry((1,))
    lru.conditional_put(key, stale)
    fresh = make_entry((2,))
    lru.conditional_put(key, fresh)

    assert lru.remove_exact(key, stale) is False
    assert lru.peek(key) is fresh
    assert lru.remove_exact(key, fresh) is True
    assert lru.peek(key) is None


_STATE_MACHINE_KEYS = st.sampled_from([make_key(f"k{index}") for index in range(4)])
_STATE_MACHINE_GENERATION_KEYS = st.sampled_from(
    [(generation,) for generation in range(5)]
)


class _WeightedLruMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.lru = WeightedLru(
            shared_budget_bytes=SHARED_BUDGET_BYTES,
            max_entry_bytes=100,
            guard=LockOrderGuard(),
        )
        self.resident_generation: dict[
            NamespaceCacheKey, tuple[NonNegativeInt, ...]
        ] = {}

    @rule(
        key=_STATE_MACHINE_KEYS,
        generation_key=_STATE_MACHINE_GENERATION_KEYS,
        weight=st.integers(min_value=1, max_value=90),
    )
    def conditional_put(
        self,
        key: NamespaceCacheKey,
        generation_key: tuple[NonNegativeInt, ...],
        weight: NonNegativeInt,
    ) -> None:
        entry = make_entry(generation_key, weight=weight)
        admitted, _displaced, _evicted = self.lru.conditional_put(key, entry)
        try:
            current = self.resident_generation[key]
        except KeyError:
            current = None
        should_admit = current is None or generation_key > current
        assert admitted is should_admit
        if admitted:
            self.resident_generation[key] = generation_key

    @rule(key=_STATE_MACHINE_KEYS)
    def touch(self, key: NamespaceCacheKey) -> None:
        self.lru.touch(key)

    @rule(key=_STATE_MACHINE_KEYS)
    def peek(self, key: NamespaceCacheKey) -> None:
        self.lru.peek(key)

    @rule(key=_STATE_MACHINE_KEYS)
    def remove_exact(self, key: NamespaceCacheKey) -> None:
        entry = self.lru.peek(key)
        if entry is not None:
            assert self.lru.remove_exact(key, entry)
            del self.resident_generation[key]

    @invariant()
    def usage_never_exceeds_the_shared_budget(self) -> None:
        used_bytes, _entry_count = self.lru.snapshot_usage()
        assert used_bytes <= self.lru.shared_budget_bytes

    @invariant()
    def resident_entries_are_never_staler_than_their_latest_submission(self) -> None:
        for key, latest_generation in self.resident_generation.items():
            entry = self.lru.peek(key)
            assert entry is not None
            assert entry.generation_key >= latest_generation


def test_weighted_lru_respects_budget_and_generation_ordering() -> None:
    run_state_machine_as_test(_WeightedLruMachine)  # type: ignore[no-untyped-call]
