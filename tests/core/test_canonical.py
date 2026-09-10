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


@pytest.mark.parametrize("value", [None, 1, "x", 1.5, b"bytes", True])
def test_canonicalize_passes_through_hashable_scalars(value: object) -> None:
    assert canonicalize(value) == value


def test_canonicalize_rejects_unhashable_unsupported_values() -> None:
    with pytest.raises(UnsupportedCacheRequestError):
        canonicalize({1, 2, 3})
