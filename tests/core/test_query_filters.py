from __future__ import annotations

from collections import UserDict
from itertools import combinations
from unittest.mock import Mock

import pytest
from bson import BSON, SON, Code, Int64, ObjectId, Regex
from bson.raw_bson import RawBSONDocument
from hypothesis import given
from hypothesis import strategies as st

from client_query_cache._core.canonical import canonicalize
from client_query_cache._core.errors import UnsupportedCacheRequestError
from client_query_cache._core.order_sensitive_keys import (
    order_sensitive_discriminator_key,
)
from client_query_cache._core.query_filters import find_filter_key

pytestmark = pytest.mark.unit


def physical_key(filter_document: object) -> object:
    return canonicalize(
        order_sensitive_discriminator_key(("find", find_filter_key(filter_document)))
    )


class CustomInt(int):
    __slots__ = ()


class CustomField(str):  # noqa: FURB189 (exercise a BSON-compatible field subtype)
    __slots__ = ()


@pytest.fixture
def custom_fields(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    monkeypatch.setattr(
        CustomField, "__lt__", Mock(side_effect=RuntimeError("custom field ordering"))
    )
    return {CustomField("b"): 2, CustomField("a"): 1}


def test_native_custom_fields_keep_ordered_fallback(
    custom_fields: dict[str, object],
) -> None:
    assert BSON.encode(custom_fields) == BSON.encode({"b": 2, "a": 1})
    assert find_filter_key(custom_fields) == order_sensitive_discriminator_key(
        custom_fields
    )
    assert physical_key(custom_fields) == canonicalize(
        order_sensitive_discriminator_key(("find", custom_fields))
    )


@given(
    predicates=st.dictionaries(
        st.text(alphabet="abcdefghijklmnopqrstuvwxyz._", min_size=1, max_size=16),
        st.none()
        | st.booleans()
        | st.integers()
        | st.floats(allow_nan=False)
        | st.text(),
        max_size=12,
    ),
    ordering=st.data(),
)
def test_scalar_permutations_share_the_complete_key(
    predicates: dict[str, object], ordering: st.DataObject
) -> None:
    shuffled = dict(ordering.draw(st.permutations(tuple(predicates.items()))))
    assert physical_key(predicates) == physical_key(shuffled)
    assert physical_key(predicates) != physical_key(UserDict(predicates))


@pytest.mark.parametrize(
    "filter_document",
    [
        {"literal": {"a": 1, "b": 2}},
        {"array": [1, 2]},
        {"tuple": (1, 2)},
        {"value": Int64(1)},
        {"value": ObjectId()},
        {"value": Regex("a")},
        {"value": Code("return true")},
        {"value": CustomInt(1)},
        {"value": b"bytes"},
        {"value": {1, 2}},
        {"$and": [{"a": 1}, {"b": 2}]},
        {"a": {"$eq": 1}},
        {1: "invalid-field"},
        SON([("a", 1), ("b", 2)]),
        UserDict({"a": 1}),
        RawBSONDocument(BSON.encode({"a": 1})),
    ],
    ids=[
        "document",
        "array",
        "tuple",
        "int64",
        "object-id",
        "regex",
        "code",
        "custom-scalar",
        "bytes",
        "uncanonicalizable",
        "logical",
        "operator",
        "non-string-field",
        "son",
        "custom-mapping",
        "raw-bson",
    ],
)
def test_declined_filters_keep_the_existing_representation(
    filter_document: object,
) -> None:
    assert find_filter_key(filter_document) == order_sensitive_discriminator_key(
        filter_document
    )


@pytest.mark.parametrize(
    ("forward", "backward"),
    [
        ({"a": {"x": 1, "y": 2}}, {"a": {"y": 2, "x": 1}}),
        ({"a": [1, 2]}, {"a": [2, 1]}),
        ({"a": [{"x": 1, "y": 2}]}, {"a": [{"y": 2, "x": 1}]}),
        ({"a": [1], "b": 2}, {"b": 2, "a": [1]}),
        ({"a": {"x": 1}, "b": 2}, {"b": 2, "a": {"x": 1}}),
        ({"$and": [{"a": 1}, {"b": 2}]}, {"$and": [{"b": 2}, {"a": 1}]}),
        ({"$or": [{"a": 1}, {"b": 2}]}, {"$or": [{"b": 2}, {"a": 1}]}),
        ({"a": 1}, {"a": {"$eq": 1}}),
    ],
    ids=[
        "document-order",
        "array-order",
        "document-in-array",
        "array-top-order",
        "document-top-order",
        "and-order",
        "or-order",
        "explicit-equality",
    ],
)
def test_fallback_and_explicit_equality_remain_distinct(
    forward: object, backward: object
) -> None:
    assert physical_key(forward) != physical_key(backward)


def test_numeric_key_distinctions_survive_full_wrapping() -> None:
    for first, second in combinations((True, 1, 1.0, Int64(1)), 2):
        assert physical_key({"a": first}) != physical_key({"a": second})


@pytest.mark.parametrize("value", [float("nan"), {1, 2}], ids=["nan", "unhashable"])
def test_existing_uncanonicalizable_values_are_not_hidden(value: object) -> None:
    with pytest.raises(UnsupportedCacheRequestError):
        physical_key({"a": value})
