from __future__ import annotations

import pytest

from mongo_client_cache._core.canonical import canonicalize
from mongo_client_cache._core.order_sensitive_keys import order_sensitive_key

pytestmark = pytest.mark.unit


def test_order_sensitive_key_distinguishes_reordered_mapping_fields() -> None:
    first = order_sensitive_key({"a": 1, "b": 2})
    second = order_sensitive_key({"b": 2, "a": 1})

    assert canonicalize(first) != canonicalize(second)


def test_order_sensitive_key_distinguishes_reordered_nested_mapping_fields() -> None:
    first = order_sensitive_key({"x": {"a": 1, "b": 2}})
    second = order_sensitive_key({"x": {"b": 2, "a": 1}})

    assert canonicalize(first) != canonicalize(second)


def test_order_sensitive_key_is_stable_for_the_same_field_order() -> None:
    first = order_sensitive_key({"a": 1, "b": 2})
    second = order_sensitive_key({"a": 1, "b": 2})

    assert canonicalize(first) == canonicalize(second)


def test_order_sensitive_key_preserves_sequence_order() -> None:
    assert canonicalize(order_sensitive_key([1, 2])) != canonicalize(
        order_sensitive_key([2, 1])
    )


@pytest.mark.parametrize("value", [None, 1, "x", 1.5, True])
def test_order_sensitive_key_passes_through_scalars(value: object) -> None:
    assert order_sensitive_key(value) == value
