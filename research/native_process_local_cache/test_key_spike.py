from __future__ import annotations

import importlib
import threading
import weakref
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol, cast

import pytest
from bson.codec_options import CodecOptions, TypeRegistry
from bson.int64 import Int64
from hypothesis import given
from hypothesis import strategies as st

from client_query_cache._core.canonical import canonicalize  # noqa: PLC2701 - Differential spike targets the private key contract.
from client_query_cache._core.codec import codec_fingerprint  # noqa: PLC2701 - Exercise the real registry identity wrapper.
from client_query_cache._core.order_sensitive_keys import (  # noqa: PLC2701 - Compare the existing discriminator contract.
    order_sensitive_discriminator_key,
    order_sensitive_key,
)
from client_query_cache._types import NonNegativeInt, PositiveFloat
from tests.core.test_canonical import bson_like_values

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Hashable, Iterator

pytestmark = pytest.mark.unit

type Snapshot = tuple[
    # LRU is empty after invalidation.
    NonNegativeInt, NonNegativeInt, NonNegativeInt, list[NonNegativeInt]
]
_COLLISION_HASH = 17
_EQUALITY_TIMEOUT_SECONDS: PositiveFloat = 5.0


class Spike(Protocol):
    def put(self, key: Hashable, value: bytes) -> NonNegativeInt: ...
    def lookup(self, key: Hashable) -> tuple[NonNegativeInt, bytes] | None: ...
    def clear(self) -> None: ...
    def snapshot(self) -> Snapshot: ...


@contextmanager
def native_owner() -> Generator[Spike]:
    native = importlib.import_module("client_query_cache._shared_index")
    owner = cast("Spike", native.ReferenceKeySpike())
    try:
        yield owner
    finally:
        owner.clear()


@pytest.fixture
def spike() -> Iterator[Spike]:
    with native_owner() as owner:
        yield owner


@pytest.fixture
def pool() -> Iterator[ThreadPoolExecutor]:
    with ThreadPoolExecutor(max_workers=1) as executor:
        yield executor


@dataclass(slots=True)
class EqualityGate:
    entered: threading.Event = field(default_factory=threading.Event)
    resume: threading.Event = field(default_factory=threading.Event)

    def block(self) -> None:
        self.entered.set()
        assert self.resume.wait(_EQUALITY_TIMEOUT_SECONDS)


@pytest.fixture
def gate() -> Iterator[EqualityGate]:
    barrier = EqualityGate()
    yield barrier
    barrier.resume.set()


class Colliding:
    __slots__ = ("__weakref__", "callback", "hash_code", "value")

    def __init__(self, value: Hashable, hash_code: int) -> None:
        self.value = value
        self.hash_code = hash_code
        self.callback: Callable[[], None] | None = None

    def __hash__(self) -> int:
        return self.hash_code

    def __eq__(self, other: object) -> bool:
        callback, self.callback = self.callback, None
        if callback is not None:
            callback()
        return self.value == (other.value if isinstance(other, Colliding) else other)


class TupleIdentity:
    __slots__ = ("anchor",)

    def __init__(self, anchor: Hashable) -> None:
        self.anchor = anchor

    def __hash__(self) -> int:
        return hash(self.anchor)

    def __eq__(self, other: object) -> bool:
        return other is self or other is self.anchor


@pytest.mark.parametrize("reverse", [False, True], ids=("native-first", "opaque-first"))
def test_compact_tuple_reconstruction_changes_supported_equality(
    *, reverse: bool
) -> None:
    native = importlib.import_module("client_query_cache._shared_index")
    anchor = canonicalize({"code": "one"})
    opaque = canonicalize(TupleIdentity(anchor))
    first, second = (opaque, anchor) if reverse else (anchor, opaque)
    assert first == second
    if reverse:
        assert native.compact_key_equal(first, second)
    else:
        assert not native.compact_key_equal(first, second)


@given(bson_like_values(), bson_like_values())
def test_reference_keys_match_canonical_equality(first: object, second: object) -> None:
    with native_owner() as owner:
        one, two = canonicalize(first), canonicalize(second)
        token = owner.put(one, b"encoded")
        assert owner.lookup(two) == ((token, b"encoded") if one == two else None)


@given(
    st.lists(
        st.tuples(
            st.sampled_from(("put", "lookup", "clear")),
            st.integers(min_value=0, max_value=7),
            st.binary(max_size=16),
        ),
        max_size=40,
    )
)
def test_collision_operation_ordering(
    operations: list[tuple[Literal["put", "lookup", "clear"], NonNegativeInt, bytes]],
) -> None:
    reference: dict[
        Hashable, tuple[NonNegativeInt, bytes]
    ] = {}  # Empty before admission and after clear.
    with native_owner() as owner:
        for operation, identity, encoded in operations:
            key = Colliding(identity, _COLLISION_HASH)
            if operation == "clear":
                owner.clear()
                reference.clear()
            elif operation == "put":
                token = owner.put(key, encoded)
                reference[key] = (token, encoded)
            else:
                try:
                    expected = reference[key]
                except KeyError:
                    expected = None
                assert owner.lookup(key) == expected


@pytest.mark.parametrize("reverse", [False, True], ids=("native-first", "opaque-first"))
@pytest.mark.parametrize(
    "value", [1, "code", b"code"], ids=("integer", "string", "bytes")
)
def test_mixed_opaque_equality(spike: Spike, value: Hashable, *, reverse: bool) -> None:
    opaque = canonicalize(Colliding(value, hash(value)))
    first, second = (opaque, value) if reverse else (value, opaque)
    token = spike.put(first, b"original")
    assert spike.lookup(second) == (token, b"original")
    replacement = spike.put(second, b"replacement")
    assert replacement > token
    assert spike.lookup(first) == (replacement, b"replacement")
    assert spike.snapshot()[3] == [replacement]


@pytest.mark.parametrize(
    "reverse", [False, True], ids=("integer-first", "subtype-first")
)
@pytest.mark.parametrize("second", [1.0, Int64(1)], ids=("float", "bson-int64"))
def test_identity_numeric_equivalence(
    spike: Spike, second: object, *, reverse: bool
) -> None:
    first_key = canonicalize(order_sensitive_key(1))
    second_key = canonicalize(order_sensitive_key(second))
    if reverse:
        first_key, second_key = second_key, first_key
    token = spike.put(first_key, b"numeric")
    assert spike.lookup(second_key) == (token, b"numeric")


@pytest.mark.parametrize("reverse", [False, True], ids=("native-first", "opaque-first"))
def test_reference_preserves_tuple_identity(spike: Spike, *, reverse: bool) -> None:
    anchor = canonicalize({"code": "one"})
    opaque = canonicalize(TupleIdentity(anchor))
    first, second = (opaque, anchor) if reverse else (anchor, opaque)
    token = spike.put(first, b"tuple")
    assert spike.lookup(second) == (token, b"tuple")


@pytest.mark.parametrize("reverse", [False, True], ids=("forward", "reverse"))
@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param(1, Int64(1), id="numeric-subtype"),
        pytest.param(True, 1, id="boolean"),
        pytest.param({"a": 1, "b": 2}, {"b": 2, "a": 1}, id="field-order"),
    ],
)
def test_discriminator_distinctions(
    spike: Spike, first: object, second: object, *, reverse: bool
) -> None:
    one = canonicalize(order_sensitive_discriminator_key(first))
    two = canonicalize(order_sensitive_discriminator_key(second))
    if reverse:
        one, two = two, one
    spike.put(one, b"first")
    assert spike.lookup(two) is None


def test_codec_registry_identity(spike: Spike) -> None:
    registry = TypeRegistry()
    first = canonicalize(codec_fingerprint(CodecOptions(type_registry=registry)))
    same = canonicalize(codec_fingerprint(CodecOptions(type_registry=registry)))
    distinct = canonicalize(
        codec_fingerprint(CodecOptions(type_registry=TypeRegistry()))
    )
    token = spike.put(first, b"codec")
    assert spike.lookup(same) == (token, b"codec")
    assert spike.lookup(distinct) is None


@pytest.mark.parametrize("operation", ["lookup", "put"], ids=("lookup", "admission"))
def test_finite_reentrant_replacement(
    spike: Spike, operation: Literal["lookup", "put"]
) -> None:
    resident = Colliding("key", _COLLISION_HASH)
    spike.put(resident, b"obsolete")

    def replace() -> None:
        spike.clear()
        spike.put(Colliding("key", _COLLISION_HASH), b"reentrant")

    resident.callback = replace
    if operation == "lookup":
        observed = spike.lookup(Colliding("key", _COLLISION_HASH))
        assert observed is not None
        assert observed[1] == b"reentrant"
        assert spike.snapshot()[1:3] == (1, 0)
    else:
        token = spike.put(Colliding("key", _COLLISION_HASH), b"outer")
        assert spike.lookup(Colliding("key", _COLLISION_HASH)) == (token, b"outer")
    assert len(spike.snapshot()[3]) == 1


@pytest.mark.parametrize("mutation", ["clear", "replace", "insert"])
@pytest.mark.parametrize("operation", ["lookup", "put"], ids=("lookup", "admission"))
def test_compared_version_is_committed(
    spike: Spike,
    pool: ThreadPoolExecutor,
    gate: EqualityGate,
    mutation: Literal["clear", "replace", "insert"],
    operation: Literal["lookup", "put"],
) -> None:
    resident = Colliding("old" if mutation == "insert" else "key", _COLLISION_HASH)
    spike.put(resident, b"obsolete")
    resident.callback = gate.block
    probe = Colliding("key", _COLLISION_HASH)
    pending = (
        pool.submit(spike.lookup, probe)
        if operation == "lookup"
        else pool.submit(spike.put, probe, b"outer")
    )
    assert gate.entered.wait(_EQUALITY_TIMEOUT_SECONDS)
    if mutation == "clear":
        spike.clear()
        expected = None
    else:
        token = spike.put(probe, b"current")
        expected = (token, b"current")
    gate.resume.set()
    committed = pending.result(timeout=_EQUALITY_TIMEOUT_SECONDS)
    if operation == "lookup":
        assert committed == expected
        assert spike.snapshot()[1:3] == ((0, 1) if expected is None else (1, 0))
    else:
        assert spike.lookup(probe) == (committed, b"outer")


class EqualityInterruptedError(Exception):
    pass


@pytest.mark.parametrize("operation", ["lookup", "put"], ids=("lookup", "admission"))
def test_exception_commits_no_pending_effects(
    spike: Spike,
    pool: ThreadPoolExecutor,
    gate: EqualityGate,
    operation: Literal["lookup", "put"],
) -> None:
    resident = Colliding("key", _COLLISION_HASH)
    spike.put(resident, b"obsolete")

    def interrupt() -> None:
        gate.block()
        raise EqualityInterruptedError

    resident.callback = interrupt
    probe = Colliding("key", _COLLISION_HASH)
    pending = (
        pool.submit(spike.lookup, probe)
        if operation == "lookup"
        else pool.submit(spike.put, probe, b"interrupted")
    )
    assert gate.entered.wait(_EQUALITY_TIMEOUT_SECONDS)
    spike.clear()
    spike.put(Colliding("key", _COLLISION_HASH), b"current")
    after_mutation = spike.snapshot()  # pytriage: TR5 (Before resuming lookup.)
    gate.resume.set()
    with pytest.raises(EqualityInterruptedError):
        pending.result(timeout=_EQUALITY_TIMEOUT_SECONDS)
    assert spike.snapshot() == after_mutation


@dataclass(slots=True)
class Reclamation:
    key: weakref.ReferenceType[Colliding]
    observations: list[Snapshot]  # Empty until the resident key is reclaimed.


def install_reclamation_probe(spike: Spike) -> Reclamation:
    key = Colliding("released", _COLLISION_HASH)
    observations: list[Snapshot] = []  # Empty until finalization.
    weakref.finalize(key, lambda: observations.append(spike.snapshot()))
    spike.put(key, b"owned")
    return Reclamation(weakref.ref(key), observations)


@pytest.fixture
def reclamation(spike: Spike) -> Reclamation:
    return install_reclamation_probe(spike)


def test_reclamation_callback_runs_outside_lock(
    spike: Spike, reclamation: Reclamation
) -> None:
    assert reclamation.key() is not None
    spike.clear()
    assert reclamation.key() is None
    assert reclamation.observations == [spike.snapshot()]
    spike.clear()
    assert len(reclamation.observations) == 1
