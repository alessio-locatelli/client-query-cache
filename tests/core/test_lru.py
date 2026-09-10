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


def test_conditional_put_rejects_older_generation(lru: WeightedLru) -> None:
    key = make_key("k")
    newer = make_entry((5,))
    lru.conditional_put(key, newer)

    admitted, displaced, evicted = lru.conditional_put(key, make_entry((3,)))

    assert not admitted
    assert displaced is None
    assert evicted == []
    assert lru.get_and_touch(key) is newer


def test_conditional_put_replaces_with_newer_generation(lru: WeightedLru) -> None:
    key = make_key("k")
    older = make_entry((1,))
    lru.conditional_put(key, older)

    newer = make_entry((2,))
    admitted, displaced, _evicted = lru.conditional_put(key, newer)

    assert admitted
    assert displaced is older
    assert lru.get_and_touch(key) is newer


def test_identity_guarded_ordering_ranks_epoch_before_identity_generation(
    lru: WeightedLru,
) -> None:
    key = make_key("k")
    stale_pre_clear = make_entry((0, 100))
    lru.conditional_put(key, stale_pre_clear)

    valid_post_clear = make_entry((1, 1))
    admitted, displaced, _evicted = lru.conditional_put(key, valid_post_clear)

    assert admitted
    assert displaced is stale_pre_clear
    assert lru.get_and_touch(key) is valid_post_clear


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
        lru.get_and_touch(protected_key)
        lru.conditional_put(make_key(index), make_entry((1,), weight=10))

    assert lru.get_and_touch(protected_key) is not None


def test_is_oversize_rejects_values_over_the_max_entry_size(lru: WeightedLru) -> None:
    assert lru.is_oversize(101)
    assert not lru.is_oversize(100)


def test_remove_exact_only_removes_the_matching_token(lru: WeightedLru) -> None:
    key = make_key("k")
    stale = make_entry((1,))
    lru.conditional_put(key, stale)
    fresh = make_entry((2,))
    lru.conditional_put(key, fresh)

    assert lru.remove_exact(key, stale) is False
    assert lru.get_and_touch(key) is fresh
    assert lru.remove_exact(key, fresh) is True
    assert lru.get_and_touch(key) is None
