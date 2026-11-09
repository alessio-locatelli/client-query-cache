from typing import TYPE_CHECKING, Literal, NewType

import pytest

from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.keys import NamespaceId, canonical_alias_key

from .conftest import SHARED_BUDGET_BYTES, SyntheticPayload

if TYPE_CHECKING:
    from client_query_cache import CacheCore

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


def _assert_resident_aliases(
    core: CacheCore, admitted: list[tuple[NamespaceId, DocumentKey]]
) -> None:
    snapshot = core.snapshot()
    assert 0 < snapshot.used_bytes <= SHARED_BUDGET_BYTES
    assert snapshot.evictions > 0
    resolvable = sum(
        core.resolve_alias(namespace, "synthetic", key, None) is not None
        for namespace, key in admitted
    )
    assert resolvable == snapshot.entry_count


def _assert_resident_usage(core: CacheCore) -> None:
    snapshot = core.snapshot()
    assert 0 < snapshot.used_bytes <= SHARED_BUDGET_BYTES
    assert snapshot.evictions > 0
    assert 0 < snapshot.entry_count < ADMISSIONS_PER_CYCLE


def _clear_and_assert_empty(
    core: CacheCore, admitted: list[tuple[NamespaceId, DocumentKey]]
) -> None:
    for namespace in NAMESPACES:
        core.clear_namespace(namespace)
    snapshot = core.snapshot()
    assert snapshot.used_bytes == 0
    assert snapshot.entry_count == 0
    assert not any(
        core.resolve_alias(namespace, "synthetic", key, None) is not None
        for namespace, key in admitted
    )


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
        admitted: list[tuple[NamespaceId, DocumentKey]] = []
        for admission in range(ADMISSIONS_PER_CYCLE):
            namespace = NAMESPACES[admission % len(NAMESPACES)]
            key = DocumentKey(f"{cycle}:{admission}")
            admitted.append((namespace, key))
            _admit_and_hit(memory_core, namespace, key, synthetic_payload, mode)
            if (admission + 1) % 16 == 0:
                _write_and_miss(memory_core, namespace, key, mode)
                _admit_and_hit(memory_core, namespace, key, synthetic_payload, mode)
            if (admission + 1) % 128 == 0:
                if mode == "identity":
                    _assert_resident_aliases(memory_core, admitted)
                else:
                    _assert_resident_usage(memory_core)
        _clear_and_assert_empty(memory_core, admitted)
    snapshot = memory_core.snapshot()
    assert snapshot.hits == CYCLES * (ADMISSIONS_PER_CYCLE + ADMISSIONS_PER_CYCLE // 16)
    assert snapshot.misses == CYCLES * ADMISSIONS_PER_CYCLE // 16
    memory_core.close()
    assert memory_core.snapshot().used_bytes == 0
    assert memory_core.snapshot().entry_count == 0
