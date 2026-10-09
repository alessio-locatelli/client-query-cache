from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from client_query_cache._core import manager as core_module
from client_query_cache._core.codec import encode_value
from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.find_reads import (
    FindReadShape,
    find_read_shape,
)
from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.manager import (
    CacheCore,
    CacheCoreConfig,
    _discard_entry_locked,
)
from client_query_cache._types import NonNegativeInt
from tests.call_counting import count_current_thread_calls
from tests.core.conftest import patch_conditional_put_hook

if TYPE_CHECKING:
    from client_query_cache._core.entries import CacheEntry
    from client_query_cache._core.keys import CacheKey
    from client_query_cache._core.lru import WeightedLru

pytestmark = pytest.mark.unit


def shape(limit: int, family: object = "family") -> FindReadShape:
    return find_read_shape(
        {"family": family}, None, {"_id": 1}, 0, limit, collation=None, codec="codec"
    )


def admit(
    core: CacheCore, namespace: NamespaceId, source: FindReadShape, marker: int = 0
) -> AdmissionOutcome:
    return core.admit_namespace(
        core.capture_namespace_generation(namespace),
        source.discriminator,
        [marker],
        find_source=source.source,
    )


@pytest.mark.parametrize(
    ("source_limit", "request_limit", "hit"),
    [
        (100, 10, True),
        (0, 10, True),
        (10, 10, True),
        (5, 10, False),
        (100, 0, False),
        (-100, 10, False),
        (100, -10, False),
        (True, 2, False),
        (100, True, False),
        (False, 10, False),
        (-10, -10, True),
    ],
    ids=[
        "covering",
        "unlimited-source",
        "exact",
        "too-small",
        "unlimited-request",
        "negative-source",
        "negative-request",
        "boolean-source",
        "boolean-request",
        "false-source",
        "negative-exact",
    ],
)
def test_find_lookup_records_one_outcome(
    core: CacheCore,
    namespace: NamespaceId,
    source_limit: int,
    request_limit: int,
    hit: bool,
) -> None:
    assert admit(core, namespace, shape(source_limit)) is AdmissionOutcome.ADMITTED
    before = core.snapshot()
    lookup = core.lookup_find(namespace, shape(request_limit))
    after = core.snapshot()
    assert lookup.hit is hit
    assert after.hits - before.hits == int(hit)
    assert after.misses - before.misses == int(not hit)
    assert after.used_bytes == before.used_bytes
    assert after.entry_count == before.entry_count


@pytest.mark.parametrize(
    "limits",
    [(0, 100, 20), (20, 100, 0), (100, 0, 20)],
    ids=["unlimited-first", "small-first", "large-first"],
)
def test_smallest_covering_source_wins(
    core: CacheCore, namespace: NamespaceId, limits: tuple[int, ...]
) -> None:
    for limit in limits:
        admit(core, namespace, shape(limit), marker=limit)
    assert core.lookup_find(namespace, shape(10)).value == [20]


@pytest.mark.parametrize(
    "limits",
    [(20,), (0,), (20, 100), (100, 20), (0, 100)],
    ids=[
        "collision-only",
        "unlimited-collision",
        "smaller-first",
        "smaller-last",
        "unlimited-first",
    ],
)
def test_family_hash_collisions_require_full_query_equality(
    core: CacheCore, namespace: NamespaceId, limits: tuple[int, ...]
) -> None:
    # Python integers -1 and -2 have the same hash but different query meanings.
    request = shape(10, family=-2)
    collision = shape(20, family=-1)
    assert request.source is not None
    assert collision.source is not None
    assert request.source.family == collision.source.family
    for limit in limits:
        family = -2 if limit == 100 else -1
        assert (
            admit(core, namespace, shape(limit, family), marker=family)
            is AdmissionOutcome.ADMITTED
        )
    lookup = core.lookup_find(namespace, request)
    assert lookup.hit is (100 in limits)
    assert lookup.value == ([-2] if 100 in limits else None)


@pytest.mark.parametrize(
    "transition",
    ["write", "clear", "create", "unavailable", "recover", "close"],
    ids=["write", "clear", "create", "unavailable", "recover", "close"],
)
def test_source_transitions(
    core: CacheCore, namespace: NamespaceId, transition: str
) -> None:
    admit(core, namespace, shape(100))
    state = core._namespace(namespace)
    if transition == "close":
        core.close()
        assert core.snapshot().entry_count == 0
        assert core._namespaces == {}
        return
    if transition == "write":
        core.record_write(namespace, 0)
    elif transition == "clear":
        core.clear_namespace(namespace)
    elif transition == "create":
        core.create_namespace(namespace)
    else:
        core.set_database_available(namespace.database, available=False)
        if transition == "recover":
            core.clear_namespace(namespace)
            core.set_database_available(namespace.database, available=True)
    assert not core.lookup_find(namespace, shape(10)).hit
    if transition != "unavailable":
        assert not state.find_families


def test_compatible_lookup_promotes_source_under_pressure(
    namespace: NamespaceId,
) -> None:
    weight = len(encode_value([0]))
    core = CacheCore(
        CacheCoreConfig(shared_budget_bytes=weight * 2, max_entry_bytes=weight)
    )
    admit(core, namespace, shape(100))
    admit(core, namespace, shape(100, "other"))
    assert core.lookup_find(namespace, shape(10)).hit
    admit(core, namespace, shape(100, "new"))
    assert core.lookup_find(namespace, shape(10)).hit
    assert not core.lookup_find(namespace, shape(10, "other")).hit
    assert len(core._namespace(namespace).find_families) == 2


def test_eviction_reclaims_an_already_invalidated_family(
    namespace: NamespaceId,
) -> None:
    weight = len(encode_value([0]))
    core = CacheCore(
        CacheCoreConfig(shared_budget_bytes=weight * 2, max_entry_bytes=weight)
    )
    admit(core, namespace, shape(100, "invalidated"))
    core.record_write(namespace, 0)
    admit(core, namespace, shape(100, "fresh-one"))
    admit(core, namespace, shape(100, "fresh-two"))
    assert not core.lookup_find(namespace, shape(10, "invalidated")).hit
    assert len(core._namespace(namespace).entry_index) == 2
    assert len(core._namespace(namespace).find_families) == 2


@pytest.mark.parametrize(
    "transition",
    ["write", "evict", "replace"],
    ids=["generation-race", "eviction-race", "replacement-race"],
)
def test_candidate_rechecks_actual_token_and_generation(
    core: CacheCore,
    namespace: NamespaceId,
    monkeypatch: pytest.MonkeyPatch,
    transition: str,
) -> None:
    admit(core, namespace, shape(20), marker=20)
    admit(core, namespace, shape(100), marker=100)
    original = type(core._lru).peek
    triggered = False

    def paused_peek(lru: WeightedLru, key: CacheKey) -> CacheEntry | None:
        nonlocal triggered
        entry = original(lru, key)
        if entry is not None and not triggered:
            triggered = True
            if transition == "write":
                core.record_write(namespace, 0)
            else:
                core._lru.remove_exact(key, entry)
                if transition == "replace":
                    admit(core, namespace, shape(20), marker=999)
                return original(lru, key)
        return entry

    monkeypatch.setattr(type(core._lru), "peek", paused_peek)
    lookup = core.lookup_find(namespace, shape(10))
    assert triggered
    if transition == "write":
        assert not lookup.hit
    else:
        assert lookup.value == [100]


@pytest.mark.parametrize(
    "transition",
    ["clear", "evict", "close"],
    ids=["clear-during-put", "evict-during-put", "close-during-put"],
)
def test_failed_publication_leaves_no_source_token(
    core: CacheCore,
    namespace: NamespaceId,
    monkeypatch: pytest.MonkeyPatch,
    transition: str,
) -> None:
    state = core._namespace(namespace)

    def hook(key: CacheKey, entry: CacheEntry) -> None:
        if transition == "clear":
            core.clear_namespace(namespace)
        elif transition == "close":
            core.close()
        else:
            core._lru.remove_exact(key, entry)

    patch_conditional_put_hook(monkeypatch, core, hook)
    assert admit(core, namespace, shape(100)) is AdmissionOutcome.DECLINED_STALE
    assert state.find_families == {}
    assert core.snapshot().entry_count == 0


def test_eviction_between_residency_check_and_publication_reclaims_token(
    core: CacheCore, namespace: NamespaceId, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = type(core._lru).contains_exact
    triggered = False

    def paused_contains(lru: WeightedLru, key: CacheKey, entry: CacheEntry) -> bool:
        nonlocal triggered
        resident = original(lru, key, entry)
        if resident and not triggered:
            triggered = True
            lru.remove_exact(key, entry)
        return resident

    monkeypatch.setattr(type(core._lru), "contains_exact", paused_contains)
    assert admit(core, namespace, shape(100)) is AdmissionOutcome.DECLINED_STALE
    assert not core._namespace(namespace).find_families
    assert not core.lookup_find(namespace, shape(10)).hit


def test_old_cleanup_preserves_new_replacement(
    core: CacheCore, namespace: NamespaceId
) -> None:
    admit(core, namespace, shape(100))
    state = core._namespace(namespace)
    old_entry = next(iter(state.entry_index))
    core.record_write(namespace, 0)
    admit(core, namespace, shape(100), marker=1)
    with core._namespace_section(state):
        _discard_entry_locked(state, old_entry)
    assert core.lookup_find(namespace, shape(10)).value == [1]
    assert sum(map(len, state.find_families.values())) == 1


@pytest.mark.parametrize(
    "unrelated", [0, 128], ids=["isolated", "unrelated-families-and-namespaces"]
)
@pytest.mark.parametrize(
    "limits",
    [
        (100,),
        tuple(range(100, 164)),
        tuple(range(163, 99, -1)),
        (0, *range(163, 99, -1)),
    ],
    ids=["single", "ascending", "descending", "unlimited-first"],
)
def test_lookup_probes_only_its_family(
    core: CacheCore,
    namespace: NamespaceId,
    monkeypatch: pytest.MonkeyPatch,
    unrelated: NonNegativeInt,
    limits: tuple[int, ...],
) -> None:
    for limit in limits:
        admit(core, namespace, shape(limit), marker=limit)
    for index in range(unrelated):
        admit(
            core,
            namespace if index % 2 else NamespaceId("other", str(index)),
            shape(100, index),
        )
    probes = count_current_thread_calls(monkeypatch, type(core._lru), "peek")
    discriminators = count_current_thread_calls(
        monkeypatch, core_module, "find_discriminator"
    )
    assert core.lookup_find(namespace, shape(10)).value == [100]
    assert probes.count == 2
    assert discriminators.count == 2


@example([("admit", limit) for limit in range(5)])
@example(
    [
        ("admit", 0),
        ("lookup", 1),
        ("write", 0),
        ("lookup", 1),
        ("admit", 10),
        ("lookup", 1),
        ("clear", 0),
    ]
)
@given(
    st.lists(
        st.tuples(
            st.sampled_from(("admit", "lookup", "write", "clear", "create", "reclaim")),
            st.integers(min_value=0, max_value=50),
        ),
        min_size=1,
        max_size=100,
    )
)
def test_generated_source_ownership_schedules(
    operations: list[tuple[str, int]],
) -> None:
    weight = len(encode_value([0]))
    core = CacheCore(
        CacheCoreConfig(shared_budget_bytes=weight * 4, max_entry_bytes=weight)
    )
    namespace = NamespaceId("generated", "sources")
    generation = 0
    for operation, limit in operations:
        if operation == "admit":
            admit(core, namespace, shape(limit), marker=generation)
        elif operation == "lookup":
            lookup = core.lookup_find(namespace, shape(max(1, limit)))
            if lookup.hit:
                assert lookup.value == [generation]
        elif operation == "write":
            core.record_write(namespace, limit)
            generation += 1
        elif operation == "clear":
            core.clear_namespace(namespace)
            generation += 1
        elif operation == "create":
            core.create_namespace(namespace)
            generation += 1
        else:
            admit(
                core,
                NamespaceId("generated", "pressure"),
                shape(limit),
                marker=generation,
            )
        state = core._namespace(namespace)
        tokens = {token for bucket in state.find_families.values() for token in bucket}
        assert tokens <= state.entry_index.keys()
        assert len(tokens) <= core.snapshot().entry_count <= 4
        assert all(
            core._lru.contains_exact(state.entry_index[token], token)
            for token in tokens
        )
        assert all(state.find_families.values())
