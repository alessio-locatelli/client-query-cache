from __future__ import annotations

from collections.abc import Mapping, Sequence

from bson.decimal128 import Decimal128
from bson.int64 import Int64

from client_query_cache._core.canonical import _CanonicalTag, _PendingTag

_MAPPING_TAG = _PendingTag("ordered-map", items=True)
_SEQUENCE_TAG = _PendingTag("ordered-seq", items=True)
_FLOAT_TAG = _PendingTag("float", items=False)
_INT64_TAG = _PendingTag("int64", items=False)
_TAG_TYPES = (_CanonicalTag, _PendingTag)
_TAGGED_TUPLE_SIZE = 2
_ORDER_INDEPENDENT_SCALAR_TYPES = (int, str, bytes, bool, type(None))


def _order_sensitive_key(
    value: object, *, distinguish_numeric_subtypes: bool
) -> object:
    if type(value) in _ORDER_INDEPENDENT_SCALAR_TYPES:
        return value
    if (
        isinstance(value, tuple)
        and len(value) == _TAGGED_TUPLE_SIZE
        and type(value[0]) in _TAG_TYPES
    ):
        return value
    if isinstance(value, Mapping):
        return (
            _MAPPING_TAG,
            tuple(
                [
                    _order_sensitive_key(
                        part, distinguish_numeric_subtypes=distinguish_numeric_subtypes
                    )
                    for pair in value.items()
                    for part in pair
                ]
            ),
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return (
            _SEQUENCE_TAG,
            tuple(
                [
                    _order_sensitive_key(
                        item, distinguish_numeric_subtypes=distinguish_numeric_subtypes
                    )
                    for item in value
                ]
            ),
        )
    if distinguish_numeric_subtypes:
        if isinstance(value, Int64):
            return (_INT64_TAG, value)
        if isinstance(value, float):
            return (_FLOAT_TAG, value)
    elif isinstance(value, Decimal128):
        return value.to_decimal()
    return value


def order_sensitive_key(value: object) -> object:
    return _order_sensitive_key(value, distinguish_numeric_subtypes=False)


def order_sensitive_discriminator_key(value: object) -> object:
    return _order_sensitive_key(value, distinguish_numeric_subtypes=True)
