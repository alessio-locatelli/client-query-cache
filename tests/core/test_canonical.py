from __future__ import annotations

import pytest

from mongo_client_cache._core.canonical import canonicalize
from mongo_client_cache._core.errors import UnsupportedCacheRequestError

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ({"a": 1, "b": 2}, {"b": 2, "a": 1}),
        ({"a": {"x": 1, "y": 2}}, {"a": {"y": 2, "x": 1}}),
    ],
)
def test_canonicalize_makes_dict_key_order_irrelevant(
    first: dict[str, object], second: dict[str, object]
) -> None:
    assert canonicalize(first) == canonicalize(second)


def test_canonicalize_preserves_list_order() -> None:
    assert canonicalize([1, 2]) != canonicalize([2, 1])


def test_canonicalize_distinguishes_nested_shapes() -> None:
    assert canonicalize({"a": 1}) != canonicalize({"a": 1, "b": 1})


@pytest.mark.parametrize("value", [None, 1, "x", 1.5, b"bytes"])
def test_canonicalize_passes_through_hashable_scalars(value: object) -> None:
    assert canonicalize(value) == value


def test_canonicalize_rejects_unhashable_unsupported_values() -> None:
    with pytest.raises(UnsupportedCacheRequestError):
        canonicalize({1, 2, 3})


def test_canonicalize_distinguishes_a_mapping_from_an_equivalent_pair_sequence() -> (
    None
):
    assert canonicalize({"a": 1}) != canonicalize([("a", 1)])


def test_canonicalize_distinguishes_a_bool_from_an_equal_int() -> None:
    assert canonicalize(True) != canonicalize(1)  # noqa: FBT003
    assert canonicalize(False) != canonicalize(0)  # noqa: FBT003


def test_canonicalize_still_treats_equal_bools_as_equal() -> None:
    assert canonicalize(True) == canonicalize(True)  # noqa: FBT003


def test_canonicalize_distinguishes_bool_and_int_dict_keys() -> None:
    assert canonicalize({True: "x"}) != canonicalize({1: "x"})


def test_canonicalize_accepts_a_mapping_with_heterogeneous_key_types() -> None:
    mixed = {True: "x", 2: "y", "z": "w"}
    canonicalize(mixed)


def test_canonicalize_heterogeneous_key_mapping_is_order_independent() -> None:
    first = {True: "x", 2: "y", "z": "w"}
    second = {"z": "w", 2: "y", True: "x"}
    assert canonicalize(first) == canonicalize(second)


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


def test_a_raw_tuple_mimicking_the_mapping_tag_does_not_collide_with_a_mapping() -> (
    None
):
    assert canonicalize(("map", (("x", 1),))) != canonicalize({"x": 1})


def test_a_raw_tuple_mimicking_the_bool_tag_does_not_collide_with_a_bool() -> None:
    assert canonicalize(("bool", True)) != canonicalize(True)  # noqa: FBT003


def test_a_tuple_with_an_unhashable_first_element_does_not_raise() -> None:
    canonicalize(({"a": 1}, "y"))
