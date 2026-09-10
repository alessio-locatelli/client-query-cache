from __future__ import annotations

import pytest

from mongo_client_cache._core.canonical import canonicalize
from mongo_client_cache._core.errors import UnsupportedCacheRequestError

pytestmark = pytest.mark.unit


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


@pytest.mark.parametrize("value", [None, 1, "x", 1.5, b"bytes"])
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
    ],
)
def test_canonicalize_rejects_unhashable_unsupported_values(value: object) -> None:
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
    assert canonicalize(once) == once
