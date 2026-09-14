from __future__ import annotations

import pytest

from mongo_client_cache._core.entries import CacheEntry
from mongo_client_cache._core.keys import NamespaceCacheKey, NamespaceId
from mongo_client_cache._core.locking import LockOrderGuard
from mongo_client_cache._core.lru import WeightedLru

pytestmark = pytest.mark.unit

NAMESPACE = NamespaceId("db", "coll")
SHARED_BUDGET_BYTES = 1_000
ENTRY_COUNT = 100


def make_entry(generation_key: tuple[int, ...], weight: int = 10) -> CacheEntry:
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
    first_generation_key: tuple[int, ...],
    second_generation_key: tuple[int, ...],
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
    weight: int,
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
