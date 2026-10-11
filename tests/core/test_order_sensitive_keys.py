from __future__ import annotations

import operator
from typing import TYPE_CHECKING, Any

import pytest
from bson.codec_options import CodecOptions
from bson.decimal128 import Decimal128
from bson.int64 import Int64
from hypothesis import example, given
from hypothesis import strategies as st

from client_query_cache._core import canonical, order_sensitive_keys
from client_query_cache._core.canonical import canonicalize, is_canonicalizable
from client_query_cache._core.codec import codec_fingerprint
from client_query_cache._core.find_one_reads import (
    find_one_read_shape,
    generic_find_one_discriminator,
)
from client_query_cache._core.order_sensitive_keys import (
    order_sensitive_discriminator_key,
    order_sensitive_key,
)
from tests.core.test_canonical import bson_like_values

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from faker import Faker

pytestmark = pytest.mark.unit

_SAFE_FLOAT_INTEGERS = st.integers(min_value=-(2**53), max_value=2**53)
_KEY_TAG_TYPES = (canonical._CanonicalTag, canonical._PendingTag)


def tuple_nodes(node: object) -> Iterator[tuple[Any, ...]]:
    if isinstance(node, tuple):
        yield node
        for item in node:
            yield from tuple_nodes(item)


@pytest.mark.parametrize(
    ("build", "first", "second"),
    [
        pytest.param(
            order_sensitive_key,
            {"a": 1, "b": 2},
            {"b": 2, "a": 1},
            id="reordered-fields",
        ),
        pytest.param(
            order_sensitive_key,
            {"x": {"a": 1, "b": 2}},
            {"x": {"b": 2, "a": 1}},
            id="reordered-nested-fields",
        ),
        pytest.param(order_sensitive_key, [1, 2], [2, 1], id="sequence-order"),
        pytest.param(
            order_sensitive_key, {"a": 1}, [["a", 1]], id="mapping-vs-pair-sequence"
        ),
        pytest.param(
            order_sensitive_discriminator_key, 1.0, 1, id="discriminator-float-vs-int"
        ),
        pytest.param(
            order_sensitive_discriminator_key,
            Int64(1),
            1,
            id="discriminator-int64-vs-int",
        ),
        pytest.param(
            order_sensitive_discriminator_key,
            {"a": 1, "b": 2},
            {"b": 2, "a": 1},
            id="discriminator-reordered-fields",
        ),
    ],
)
def test_order_sensitive_keys_distinguish(
    build: Callable[[object], object], first: object, second: object
) -> None:
    assert canonicalize(build(first)) != canonicalize(build(second))


@pytest.mark.parametrize("value", [None, 1, "x", 1.5, True])
def test_order_sensitive_key_passes_through_scalars(value: object) -> None:
    assert order_sensitive_key(value) == value


@pytest.mark.parametrize(
    ("value", "equivalent"),
    [
        pytest.param({"a": 1, "b": 2}, {"a": 1, "b": 2}, id="same-field-order"),
        pytest.param(1.0, 1, id="float"),
        pytest.param(Int64(1), 1, id="int64"),
        pytest.param(Decimal128("1"), 1, id="decimal"),
        pytest.param(Decimal128("1.0"), 1, id="decimal-trailing-zero"),
        pytest.param({"n": Decimal128("1")}, {"n": 1}, id="embedded-decimal"),
    ],
)
def test_order_sensitive_key_shares_one_key_between_equivalent_identities(
    value: object, equivalent: object
) -> None:
    key = canonicalize(order_sensitive_key(value))
    equivalent_key = canonicalize(order_sensitive_key(equivalent))

    assert key == equivalent_key
    assert hash(key) == hash(equivalent_key)


@pytest.mark.parametrize(
    "value",
    [Decimal128("NaN"), Decimal128("sNaN")],
    ids=["quiet-nan", "signaling-nan"],
)
def test_order_sensitive_key_rejects_non_reflexive_decimal_identities(
    value: Decimal128,
) -> None:
    assert not is_canonicalizable(order_sensitive_key(value))


@given(st.data())
def test_order_sensitive_key_differs_exactly_when_relative_key_order_changes(
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
    order_changed = list(items) != list(permuted)

    original_key = canonicalize(order_sensitive_key(dict(items)))
    permuted_key = canonicalize(order_sensitive_key(dict(permuted)))

    assert (original_key != permuted_key) == order_changed


@given(value=_SAFE_FLOAT_INTEGERS)
@example(value=0)
def test_order_sensitive_discriminator_key_distinguishes_equal_valued_numeric_subtypes(
    value: int,
) -> None:
    int_key = order_sensitive_key(value)
    float_key = order_sensitive_key(float(value))
    int64_key = order_sensitive_key(Int64(value))
    decimal_key = order_sensitive_key(Decimal128(str(value)))
    assert (
        canonicalize(int_key)
        == canonicalize(float_key)
        == canonicalize(int64_key)
        == canonicalize(decimal_key)
    )
    assert hash(canonicalize(decimal_key)) == hash(canonicalize(int_key))

    int_discriminator_key = order_sensitive_discriminator_key(value)
    float_discriminator_key = order_sensitive_discriminator_key(float(value))
    int64_discriminator_key = order_sensitive_discriminator_key(Int64(value))
    assert canonicalize(int_discriminator_key) != canonicalize(float_discriminator_key)
    assert canonicalize(int_discriminator_key) != canonicalize(int64_discriminator_key)
    assert not is_canonicalizable(
        order_sensitive_discriminator_key(Decimal128(str(value)))
    )
    assert canonicalize(float_discriminator_key) != canonicalize(
        int64_discriminator_key
    )


def test_generic_find_one_filter_key_of_one_field_is_one_mapping_node(
    faker: Faker,
) -> None:
    field, value = faker.pystr(), faker.pystr()

    assert canonicalize(order_sensitive_discriminator_key({field: value})) == (
        order_sensitive_keys._MAPPING_TAG.canonical,
        (field, value),
    )


@pytest.mark.parametrize(
    ("make_value", "tag"),
    [
        pytest.param(
            lambda faker: {faker.pystr(): faker.pystr()},
            order_sensitive_keys._MAPPING_TAG,
            id="embedded-document",
        ),
        pytest.param(
            lambda faker: [faker.pystr(), faker.pyint()],
            order_sensitive_keys._SEQUENCE_TAG,
            id="array",
        ),
        pytest.param(
            lambda faker: faker.pyfloat(), order_sensitive_keys._FLOAT_TAG, id="double"
        ),
        pytest.param(
            lambda faker: Int64(faker.pyint()),
            order_sensitive_keys._INT64_TAG,
            id="int64",
        ),
    ],
)
def test_nested_order_sensitive_values_form_one_tagged_node(
    faker: Faker,
    make_value: Callable[[Faker], object],
    tag: canonical._PendingTag,
) -> None:
    filter_key = canonicalize(
        order_sensitive_discriminator_key({faker.pystr(): make_value(faker)})
    )
    read_shape = canonicalize(
        find_one_read_shape(None, None, None, codec_fingerprint(CodecOptions()))
    )
    key = canonicalize(generic_find_one_discriminator(filter_key, read_shape, 0))

    assert isinstance(filter_key, tuple)
    assert filter_key[1][1][0] is tag.canonical
    assert not any(
        node[0] is canonical._SEQUENCE_TAG and type(node[1][0]) in _KEY_TAG_TYPES
        for node in tuple_nodes(key)
        if len(node) == canonical._TAGGED_TUPLE_SIZE
    )
