from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations, pairwise
from typing import TYPE_CHECKING

import pytest
from bson.decimal128 import Decimal128
from bson.int64 import Int64
from hypothesis import given
from hypothesis import strategies as st

from client_query_cache._core.canonical import canonicalize
from client_query_cache._core.errors import UnsupportedCacheRequestError
from client_query_cache._core.order_sensitive_keys import (
    order_sensitive_discriminator_key,
    order_sensitive_key,
)
from client_query_cache._core.query_filters import find_filter_key
from tests.core.legacy_keys import (
    legacy_canonicalize,
    legacy_find_filter_key,
    legacy_order_sensitive_discriminator_key,
    legacy_order_sensitive_key,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Hashable, Iterable, Sequence

pytestmark = pytest.mark.unit


@dataclass(frozen=True, slots=True)
class _KeyAlgorithm:
    canonicalize: Callable[[object], Hashable]
    order_sensitive_key: Callable[[object], object]
    order_sensitive_discriminator_key: Callable[[object], object]
    find_filter_key: Callable[[object], object]


type _Build = Callable[[_KeyAlgorithm, object], Hashable]
type _Arrange = Callable[[Sequence[object]], Iterable[object]]

_CURRENT = _KeyAlgorithm(
    canonicalize,
    order_sensitive_key,
    order_sensitive_discriminator_key,
    find_filter_key,
)
_LEGACY = _KeyAlgorithm(
    legacy_canonicalize,
    legacy_order_sensitive_key,
    legacy_order_sensitive_discriminator_key,
    legacy_find_filter_key,
)
_COLLISION_PRONE_LEAVES = st.sampled_from(
    (
        None,
        True,
        False,
        0,
        1,
        0.0,
        -0.0,
        1.0,
        float("nan"),
        Int64(0),
        Int64(1),
        Decimal128("1"),
        Decimal128("1.0"),
        Decimal128("NaN"),
        "a",
        "b",
    )
)
_BATCHES = st.lists(
    st.recursive(
        _COLLISION_PRONE_LEAVES,
        lambda children: (
            st.lists(children, max_size=3)
            | st.tuples(children, children)
            | st.dictionaries(st.sampled_from(("a", "b")), children, max_size=2)
        ),
        max_leaves=10,
    ),
    min_size=2,
    max_size=8,
)
_REJECTED = object()


def _unordered_key(algorithm: _KeyAlgorithm, value: object) -> Hashable:
    return algorithm.canonicalize(value)


def _order_sensitive_key(algorithm: _KeyAlgorithm, value: object) -> Hashable:
    return algorithm.canonicalize(algorithm.order_sensitive_key(value))


def _discriminator_key(algorithm: _KeyAlgorithm, value: object) -> Hashable:
    return algorithm.canonicalize(algorithm.order_sensitive_discriminator_key(value))


def _find_filter_key(algorithm: _KeyAlgorithm, value: object) -> Hashable:
    return algorithm.canonicalize(
        algorithm.order_sensitive_discriminator_key(
            ("find", algorithm.find_filter_key(value))
        )
    )


def _nested_find_one_key(algorithm: _KeyAlgorithm, value: object) -> Hashable:
    assert isinstance(value, tuple)
    first, second = value
    return algorithm.canonicalize(
        algorithm.order_sensitive_discriminator_key(
            (
                "find_one_generic",
                _discriminator_key(algorithm, first),
                _discriminator_key(algorithm, second),
                0,
            )
        )
    )


_BUILDERS = pytest.mark.parametrize(
    ("build", "arrange"),
    [
        pytest.param(_unordered_key, tuple, id="unordered"),
        pytest.param(_order_sensitive_key, tuple, id="order-sensitive"),
        pytest.param(_discriminator_key, tuple, id="discriminator"),
        pytest.param(_find_filter_key, tuple, id="find-filter"),
        pytest.param(_nested_find_one_key, pairwise, id="nested-find-one"),
    ],
)


def _key(algorithm: _KeyAlgorithm, build: _Build, value: object) -> object:
    try:
        return build(algorithm, value)
    except UnsupportedCacheRequestError:
        return _REJECTED


def _references(tree: object, target: object) -> bool:
    return tree is target or (
        isinstance(tree, tuple) and any(_references(item, target) for item in tree)
    )


@_BUILDERS
@given(values=_BATCHES)
def test_compact_keys_preserve_legacy_equality_classes(
    build: _Build, arrange: _Arrange, values: list[object]
) -> None:
    inputs = tuple(arrange(values))
    current = [_key(_CURRENT, build, value) for value in inputs]
    legacy = [_key(_LEGACY, build, value) for value in inputs]

    assert [key is _REJECTED for key in current] == [key is _REJECTED for key in legacy]
    accepted = [index for index, key in enumerate(current) if key is not _REJECTED]
    for first, second in combinations(accepted, 2):
        equal = current[first] == current[second]
        assert equal == (legacy[first] == legacy[second])
        if equal:
            assert hash(current[first]) == hash(current[second])


@_BUILDERS
@given(values=_BATCHES)
def test_compact_keys_are_reused_by_later_canonicalization(
    build: _Build, arrange: _Arrange, values: list[object]
) -> None:
    for value in arrange(values):
        key = _key(_CURRENT, build, value)
        if key is _REJECTED:
            continue
        assert canonicalize(key) is key
        assert _references(
            canonicalize(order_sensitive_discriminator_key(("w", key))), key
        )
