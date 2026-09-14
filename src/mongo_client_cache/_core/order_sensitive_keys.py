from __future__ import annotations

from collections.abc import Mapping, Sequence

from bson.int64 import Int64

from mongo_client_cache._core.canonical import _OWN_TAGS as _CANONICAL_OWN_TAGS


class _OrderTag:
    __slots__ = ()


_MAPPING_TAG = _OrderTag()
_SEQUENCE_TAG = _OrderTag()
_FLOAT_TAG = _OrderTag()
_INT64_TAG = _OrderTag()
_OWN_TAGS = (_MAPPING_TAG, _SEQUENCE_TAG, _FLOAT_TAG, _INT64_TAG, *_CANONICAL_OWN_TAGS)
_TAGGED_TUPLE_SIZE = 2


def _order_sensitive_key(
    value: object, *, distinguish_numeric_subtypes: bool
) -> object:
    if (
        isinstance(value, tuple)
        and len(value) == _TAGGED_TUPLE_SIZE
        and any(value[0] is tag for tag in _OWN_TAGS)
    ):
        return value
    if isinstance(value, Mapping):
        return (
            _MAPPING_TAG,
            tuple(
                (
                    _order_sensitive_key(
                        key, distinguish_numeric_subtypes=distinguish_numeric_subtypes
                    ),
                    _order_sensitive_key(
                        item, distinguish_numeric_subtypes=distinguish_numeric_subtypes
                    ),
                )
                for key, item in value.items()
            ),
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return (
            _SEQUENCE_TAG,
            tuple(
                _order_sensitive_key(
                    item, distinguish_numeric_subtypes=distinguish_numeric_subtypes
                )
                for item in value
            ),
        )
    if distinguish_numeric_subtypes:
        if isinstance(value, Int64):
            return (_INT64_TAG, value)
        if isinstance(value, float):
            return (_FLOAT_TAG, value)
    return value


def order_sensitive_key(value: object) -> object:
    return _order_sensitive_key(value, distinguish_numeric_subtypes=False)


def order_sensitive_discriminator_key(value: object) -> object:
    return _order_sensitive_key(value, distinguish_numeric_subtypes=True)
