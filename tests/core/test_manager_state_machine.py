from __future__ import annotations

from collections import defaultdict

import pytest
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    invariant,
    rule,
    run_state_machine_as_test,
)

from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.find_one_reads import (
    find_one_read_shape,
    generic_find_one_discriminator,
)
from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.manager import CacheCore
from client_query_cache._types import NonNegativeInt

pytestmark = pytest.mark.unit

_NAMESPACES = [
    NamespaceId("state_machine_db", "coll_a"),
    NamespaceId("state_machine_db", "coll_b"),
]
_IDENTITIES = ["id-0", "id-1", "id-2", "id-3"]
_READ_SHAPES = ["shape-a", "shape-b"]
_DISCRIMINATORS = [
    "disc-a",
    "disc-b",
    generic_find_one_discriminator(
        {"rank": {"$gte": 1}}, find_one_read_shape(None, None, None, "codec"), 0
    ),
    generic_find_one_discriminator(
        {},
        find_one_read_shape(
            {"rank": 1}, [("rank", -1)], {"locale": "en", "strength": 2}, "codec"
        ),
        0,
    ),
]
_VALUES = st.integers(min_value=-1_000, max_value=1_000)
_NAMESPACE_STRATEGY = st.sampled_from(_NAMESPACES)
_IDENTITY_STRATEGY = st.sampled_from(_IDENTITIES)
_READ_SHAPE_STRATEGY = st.sampled_from(_READ_SHAPES)
_DISCRIMINATOR_STRATEGY = st.sampled_from(_DISCRIMINATORS)


class _CacheCoreMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.core = CacheCore()
        self.namespace_generation: dict[NamespaceId, NonNegativeInt] = defaultdict(int)
        self.identity_epoch: dict[tuple[NamespaceId, str], NonNegativeInt] = (
            defaultdict(int)
        )
        self.identity_values: dict[
            tuple[NamespaceId, str, str], tuple[int, NonNegativeInt]
        ] = {}
        self.namespace_values: dict[
            tuple[NamespaceId, object], tuple[object, NonNegativeInt]
        ] = {}
        self.resident_identity_keys: set[tuple[NamespaceId, str, str]] = set()
        self.resident_namespace_keys: set[tuple[NamespaceId, object]] = set()

    @rule(
        namespace=_NAMESPACE_STRATEGY,
        identity=_IDENTITY_STRATEGY,
        read_shape=_READ_SHAPE_STRATEGY,
        value=_VALUES,
    )
    def begin_and_admit_identity(
        self, namespace: NamespaceId, identity: str, read_shape: str, value: int
    ) -> None:
        capture = self.core.begin_identity_admission(namespace, identity)
        outcome = self.core.admit_identity(capture, read_shape, value)
        assert outcome in {
            AdmissionOutcome.ADMITTED,
            AdmissionOutcome.DECLINED_STALE,
        }
        key = (namespace, identity, read_shape)
        if outcome is AdmissionOutcome.ADMITTED:
            self.identity_values[key] = (
                value,
                self.identity_epoch[namespace, identity],
            )
        self.resident_identity_keys.add(key)

    @rule(namespace=_NAMESPACE_STRATEGY, identity=_IDENTITY_STRATEGY)
    def begin_and_discard_identity(self, namespace: NamespaceId, identity: str) -> None:
        capture = self.core.begin_identity_admission(namespace, identity)
        self.core.discard_identity_admission(capture)

    @rule(
        namespace=_NAMESPACE_STRATEGY,
        discriminator=_DISCRIMINATOR_STRATEGY,
        value=st.one_of(_VALUES, st.none()),
    )
    def capture_and_admit_namespace(
        self, namespace: NamespaceId, discriminator: object, value: object
    ) -> None:
        capture = self.core.capture_namespace_generation(namespace)
        outcome = self.core.admit_namespace(capture, discriminator, value)
        assert outcome in {
            AdmissionOutcome.ADMITTED,
            AdmissionOutcome.DECLINED_STALE,
        }
        key = (namespace, discriminator)
        if outcome is AdmissionOutcome.ADMITTED:
            self.namespace_values[key] = (value, self.namespace_generation[namespace])
        self.resident_namespace_keys.add(key)

    @rule(namespace=_NAMESPACE_STRATEGY, identity=_IDENTITY_STRATEGY)
    def record_write(self, namespace: NamespaceId, identity: str) -> None:
        self.core.record_write(namespace, identity)
        self.namespace_generation[namespace] += 1
        self.identity_epoch[namespace, identity] += 1

    @rule(namespace=_NAMESPACE_STRATEGY)
    def clear_namespace(self, namespace: NamespaceId) -> None:
        self.core.clear_namespace(namespace)
        self.namespace_generation[namespace] += 1
        for identity in _IDENTITIES:
            self.identity_epoch[namespace, identity] += 1
        self.resident_identity_keys = {
            key for key in self.resident_identity_keys if key[0] != namespace
        }
        self.resident_namespace_keys = {
            key for key in self.resident_namespace_keys if key[0] != namespace
        }

    @invariant()
    def no_lookup_returns_a_value_superseded_by_a_later_write_or_clear(self) -> None:
        for namespace in _NAMESPACES:
            for identity in _IDENTITIES:
                for read_shape in _READ_SHAPES:
                    identity_key = (namespace, identity, read_shape)
                    try:
                        expected_identity = self.identity_values[identity_key]
                    except KeyError:
                        expected_identity = None
                    identity_valid = (
                        expected_identity is not None
                        and expected_identity[1]
                        == self.identity_epoch[namespace, identity]
                    )
                    identity_result = self.core.lookup_identity(
                        namespace, identity, read_shape
                    )
                    if identity_valid:
                        assert expected_identity is not None
                        assert identity_result.hit
                        assert identity_result.value == expected_identity[0]
                    else:
                        assert not identity_result.hit
            for discriminator in _DISCRIMINATORS:
                namespace_key = (namespace, discriminator)
                try:
                    expected_namespace = self.namespace_values[namespace_key]
                except KeyError:
                    expected_namespace = None
                namespace_valid = (
                    expected_namespace is not None
                    and expected_namespace[1] == self.namespace_generation[namespace]
                )
                namespace_result = self.core.lookup_namespace(namespace, discriminator)
                if namespace_valid:
                    assert expected_namespace is not None
                    assert namespace_result.hit
                    assert namespace_result.value == expected_namespace[0]
                else:
                    assert not namespace_result.hit

    @invariant()
    def resident_entry_count_matches_keys_admitted_since_their_last_clear(
        self,
    ) -> None:
        expected = len(self.resident_identity_keys) + len(self.resident_namespace_keys)
        assert self.core.snapshot().entry_count == expected


def test_cache_core_admission_lookup_and_clear_ordering() -> None:
    run_state_machine_as_test(_CacheCoreMachine)  # type: ignore[no-untyped-call]
