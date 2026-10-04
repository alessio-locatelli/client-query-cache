from collections import Counter
from typing import TYPE_CHECKING, Literal, NewType

import pytest

from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.keys import NamespaceId, canonical_alias_key

from .conftest import SHARED_BUDGET_BYTES, SyntheticPayload

if TYPE_CHECKING:
    from client_query_cache._core.manager import CacheCore

pytestmark = [pytest.mark.memory, pytest.mark.usefixtures("require_memory_profiling")]

type AdmissionMode = Literal["identity", "namespace"]
DocumentKey = NewType("DocumentKey", str)
NAMESPACES = (NamespaceId("memory", "first"), NamespaceId("memory", "second"))
CYCLES = 8
ADMISSIONS_PER_CYCLE = 1024


def _admit_and_hit(
    core: CacheCore,
    namespace: NamespaceId,
    key: DocumentKey,
    payload: SyntheticPayload,
    mode: AdmissionMode,
) -> None:
    document = {"_id": key, "payload": payload}
    if mode == "identity":
        outcome = core.admit_identity(
            core.begin_identity_admission(namespace, key),
            "full",
            document,
            alias=canonical_alias_key("synthetic", key, None),
        )
        assert outcome is AdmissionOutcome.ADMITTED
        assert core.resolve_alias(namespace, "synthetic", key, None) == key
        lookup = core.lookup_identity(namespace, key, "full")
    else:
        outcome = core.admit_namespace(
            core.capture_namespace_generation(namespace), key, document
        )
        assert outcome is AdmissionOutcome.ADMITTED
        lookup = core.lookup_namespace(namespace, key)
    assert lookup.hit
    assert lookup.value == document


def _write_and_miss(
    core: CacheCore, namespace: NamespaceId, key: DocumentKey, mode: AdmissionMode
) -> None:
    core.record_write(namespace, key)
    if mode == "identity":
        assert core.resolve_alias(namespace, "synthetic", key, None) is None
        assert not core.lookup_identity(namespace, key, "full").hit
    else:
        assert not core.lookup_namespace(namespace, key).hit


def _assert_resident_metadata(core: CacheCore) -> None:
    snapshot = core.snapshot()
    assert 0 < snapshot.used_bytes <= SHARED_BUDGET_BYTES
    assert snapshot.evictions > 0
    assert sum(len(core._namespace(ns).entry_index) for ns in NAMESPACES) == (
        snapshot.entry_count
    )
    for namespace in NAMESPACES:
        state = core._namespace(namespace)
        resident_identities = Counter(
            entry.identity for entry in state.entry_index if entry.identity is not None
        )
        assert state.identities.keys() == resident_identities.keys()
        for entry, cache_key in state.entry_index.items():
            assert core._lru.contains_exact(cache_key, entry)
        for identity, identity_state in state.identities.items():
            assert identity_state.inflight_ref_count == 0
            assert identity_state.cached_ref_count == resident_identities[identity]
            assert identity_state.alias_keys == {
                alias for alias, owner in state.aliases.items() if owner == identity
            }
        assert all(owner in resident_identities for owner in state.aliases.values())


def _clear_and_assert_empty(core: CacheCore) -> None:
    for namespace in NAMESPACES:
        core.clear_namespace(namespace)
        state = core._namespace(namespace)
        assert not state.entry_index
        assert not state.identities
        assert not state.aliases
    snapshot = core.snapshot()
    assert snapshot.used_bytes == 0
    assert snapshot.entry_count == 0


@pytest.mark.parametrize(
    "mode",
    [
        pytest.param("identity", marks=pytest.mark.limit_memory("7 MB")),
        pytest.param("namespace", marks=pytest.mark.limit_memory("7 MB")),
    ],
    ids=("identity-with-alias", "namespace"),
)
def test_cache_churn(
    memory_core: CacheCore, synthetic_payload: SyntheticPayload, mode: AdmissionMode
) -> None:
    for cycle in range(CYCLES):
        for admission in range(ADMISSIONS_PER_CYCLE):
            namespace = NAMESPACES[admission % len(NAMESPACES)]
            key = DocumentKey(f"{cycle}:{admission}")
            _admit_and_hit(memory_core, namespace, key, synthetic_payload, mode)
            if (admission + 1) % 16 == 0:
                _write_and_miss(memory_core, namespace, key, mode)
                _admit_and_hit(memory_core, namespace, key, synthetic_payload, mode)
            if (admission + 1) % 128 == 0:
                _assert_resident_metadata(memory_core)
        _clear_and_assert_empty(memory_core)
    snapshot = memory_core.snapshot()
    assert snapshot.hits == CYCLES * (ADMISSIONS_PER_CYCLE + ADMISSIONS_PER_CYCLE // 16)
    assert snapshot.misses == CYCLES * ADMISSIONS_PER_CYCLE // 16
    memory_core.close()
    assert memory_core.snapshot().used_bytes == 0
    assert memory_core.snapshot().entry_count == 0
