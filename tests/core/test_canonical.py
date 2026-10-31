from __future__ import annotations

import operator
from typing import TYPE_CHECKING

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from client_query_cache._core.canonical import (
    _reference_canonicalize,
    canonicalize,
)
from client_query_cache._core.errors import UnsupportedCacheRequestError
from client_query_cache._core.order_sensitive_keys import order_sensitive_key
from tests.key_inputs import key_inputs, outcome, same_outcome, strictly_equal

if TYPE_CHECKING:
    from collections.abc import Callable

pytestmark = pytest.mark.unit

_BSON_LIKE_LEAVES = (
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(allow_nan=False)
    | st.text(max_size=8)
)


def bson_like_values() -> st.SearchStrategy[object]:
    return st.recursive(
        _BSON_LIKE_LEAVES,
        lambda children: (
            st.lists(children, max_size=5)
            | st.dictionaries(st.text(max_size=8), children, max_size=5)
        ),
        max_leaves=10,
    )


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param({"a": 1, "b": 2}, {"b": 2, "a": 1}, id="dict_key_order"),
        pytest.param(
            {"a": {"x": 1, "y": 2}}, {"a": {"y": 2, "x": 1}}, id="nested_dict_key_order"
        ),
        pytest.param(True, True, id="equal_bools"),
        pytest.param(
            {True: "x", 2: "y", "z": "w"},
            {"z": "w", 2: "y", True: "x"},
            id="heterogeneous_key_order",
        ),
        pytest.param(
            1.0,
            1,
            id="float_and_int_are_the_same_identity_mongodb_would_match",
        ),
    ],
)
def test_canonicalize_treats_as_equivalent(first: object, second: object) -> None:
    assert canonicalize(first) == canonicalize(second)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param([1, 2], [2, 1], id="list_order"),
        pytest.param({"a": 1}, {"a": 1, "b": 1}, id="nested_shape"),
        pytest.param(True, 1, id="bool_vs_int"),
        pytest.param(False, 0, id="bool_vs_int_falsy"),
        pytest.param(
            {True: "x"},
            {1: "x"},
            id="bool_vs_int_dict_key",
        ),
        pytest.param(("map", (("x", 1),)), {"x": 1}, id="forged_mapping_tag"),
        pytest.param(
            ("bool", True),
            True,
            id="forged_bool_tag",
        ),
    ],
)
def test_canonicalize_distinguishes(first: object, second: object) -> None:
    assert canonicalize(first) != canonicalize(second)


@pytest.mark.parametrize(
    "value",
    [
        pytest.param({True: "x", 2: "y", "z": "w"}, id="heterogeneous_keys"),
        pytest.param(({"a": 1}, "y"), id="unhashable_first_tuple_element"),
    ],
)
def test_canonicalize_does_not_raise(value: object) -> None:
    canonicalize(value)


@pytest.mark.parametrize("value", [None, 1, "x", b"bytes", 1.5])
def test_canonicalize_passes_through_hashable_scalars(value: object) -> None:
    assert canonicalize(value) == value


class _Unhashable:
    __slots__ = ()
    __hash__ = None  # type: ignore[assignment]


@pytest.mark.parametrize(
    "value",
    [
        pytest.param({1, 2, 3}, id="a_set"),
        pytest.param(_Unhashable(), id="a_custom_object_with_no_hash"),
        pytest.param(float("nan"), id="nan_is_not_reflexive"),
    ],
)
def test_canonicalize_rejects_values_unsuitable_as_cache_keys(value: object) -> None:
    with pytest.raises(UnsupportedCacheRequestError):
        canonicalize(value)


@pytest.mark.parametrize(
    "value",
    [
        {"a": 1, "b": [1, 2]},
        [1, {"a": 1}],
        True,
    ],
)
def test_canonicalize_is_idempotent_on_its_own_output(value: object) -> None:
    once = canonicalize(value)
    assert canonicalize(once) is once


@given(bson_like_values())
def test_canonicalize_is_idempotent_for_generated_bson_like_structures(
    value: object,
) -> None:
    once = canonicalize(value)
    assert canonicalize(once) is once


@given(st.data())
def test_canonicalize_is_unchanged_by_reordering_a_mappings_top_level_keys(
    hypothesis_data: st.DataObject,
) -> None:
    items = hypothesis_data.draw(
        st.lists(
            st.tuples(st.text(max_size=8), bson_like_values()),
            max_size=6,
            unique_by=operator.itemgetter(0),
        )
    )
    permuted = hypothesis_data.draw(st.permutations(items))
    assert canonicalize(dict(items)) == canonicalize(dict(permuted))


@given(bool_value=st.booleans(), int_value=st.integers())
@example(bool_value=True, int_value=1)
@example(bool_value=False, int_value=0)
def test_canonicalize_never_conflates_a_bool_and_an_int(
    bool_value: bool, int_value: int
) -> None:
    assert canonicalize(bool_value) != canonicalize(int_value)


@given(key_inputs())
@example({"it's": 1, "a": 2, 3: 4, True: 5})
@example({"\ud800": 1, "é": 2, "e": 3})
@example([float("nan")])
@example({1, 2})
@example(_reference_canonicalize({"a": [1, True]}))
@example(order_sensitive_key({"a": [1.5, {"b": None}]}))
def test_native_canonicalization_matches_the_reference(value: object) -> None:
    assert same_outcome(
        outcome(canonicalize, value), outcome(_reference_canonicalize, value)
    )


class _Ordered(str):  # noqa: FURB189 - repr() must return a str subclass with its own ordering.
    __slots__ = ()

    def __lt__(self, other: object) -> bool:
        return str(other) < str(self)


class _ReversedRepr:
    __slots__ = ("value",)

    def __init__(self, value: str) -> None:
        self.value = value

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _ReversedRepr) and other.value == self.value

    def __repr__(self) -> str:
        return _Ordered(self.value)


def test_mapping_keys_with_custom_repr_ordering_sort_like_the_reference() -> None:
    value = {_ReversedRepr(name): name for name in ("a", "c", "b")}
    expected = _reference_canonicalize(value)
    assert isinstance(expected, tuple)
    assert strictly_equal(canonicalize(value), expected)
    assert [pair[1] for pair in expected[1]] == ["c", "b", "a"]


class _Leaf:
    __slots__ = ("effect", "hash_error", "unequal")

    def __init__(
        self,
        effect: Callable[[], object] | None = None,
        *,
        hash_error: Exception | None = None,
        unequal: Exception | bool = False,
    ) -> None:
        self.effect = effect
        self.hash_error = hash_error
        self.unequal = unequal

    def __hash__(self) -> int:
        if self.effect is not None:
            self.effect()
        if self.hash_error is not None:
            raise self.hash_error
        return 0

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Leaf)

    def __ne__(self, other: object) -> bool:
        if isinstance(self.unequal, Exception):
            raise self.unequal
        return self.unequal


def _appending_leaf() -> object:
    tail: list[object] = [1]
    return {"leaf": _Leaf(lambda: tail.append(2)), "tail": tail}


def _resizing_leaf() -> object:
    value: dict[str, object] = {}
    value["leaf"] = _Leaf(lambda: value.update(extra=1))
    value["tail"] = 1
    return value


@pytest.mark.parametrize(
    "build",
    [
        _appending_leaf,
        _resizing_leaf,
        lambda: [_Leaf(hash_error=ValueError("hash failed"))],
        lambda: [_Leaf(hash_error=TypeError("not hashable"))],
        lambda: {"leaf": _Leaf(unequal=ValueError("comparison failed"))},
        lambda: {"leaf": _Leaf(unequal=True)},
    ],
    ids=[
        "appending",
        "resizing",
        "raising-hash",
        "unhashable",
        "raising-ne",
        "nan-like",
    ],
)
def test_reentrant_and_raising_leaves_match_the_reference(
    build: Callable[[], object],
) -> None:
    assert same_outcome(
        outcome(canonicalize, build()), outcome(_reference_canonicalize, build())
    )
