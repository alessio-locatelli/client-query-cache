from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence

from bson.decimal128 import Decimal128
from bson.int64 import Int64

from client_query_cache._core.errors import UnsupportedCacheRequestError


class _LegacyTag:
    __slots__ = ()


_CANONICAL_MAPPING_TAG = _LegacyTag()
_CANONICAL_SEQUENCE_TAG = _LegacyTag()
_CANONICAL_BOOL_TAG = _LegacyTag()
_CANONICAL_OWN_TAGS = (
    _CANONICAL_MAPPING_TAG,
    _CANONICAL_SEQUENCE_TAG,
    _CANONICAL_BOOL_TAG,
)
_ORDER_MAPPING_TAG = _LegacyTag()
_ORDER_SEQUENCE_TAG = _LegacyTag()
_ORDER_FLOAT_TAG = _LegacyTag()
_ORDER_INT64_TAG = _LegacyTag()
_ORDER_OWN_TAGS = (
    _ORDER_MAPPING_TAG,
    _ORDER_SEQUENCE_TAG,
    _ORDER_FLOAT_TAG,
    _ORDER_INT64_TAG,
    *_CANONICAL_OWN_TAGS,
)
_SCALAR_PREDICATES = _LegacyTag()
_SCALAR_TYPES = (bool, int, float, str)
_TAGGED_TUPLE_SIZE = 2


def legacy_canonicalize(value: object) -> Hashable:
    if (
        isinstance(value, tuple)
        and len(value) == _TAGGED_TUPLE_SIZE
        and any(value[0] is tag for tag in _CANONICAL_OWN_TAGS)
    ):
        return value
    if isinstance(value, Mapping):
        pairs = [
            (legacy_canonicalize(key), legacy_canonicalize(item))
            for key, item in value.items()
        ]
        items = tuple(sorted(pairs, key=lambda pair: repr(pair[0])))
        return (_CANONICAL_MAPPING_TAG, items)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return (
            _CANONICAL_SEQUENCE_TAG,
            tuple(legacy_canonicalize(item) for item in value),
        )
    if isinstance(value, bool):
        return (_CANONICAL_BOOL_TAG, value)
    try:
        hash(value)
    except TypeError:
        type_name = type(value).__name__
        message = f"cannot canonicalize value of type {type_name!r} for a cache key"
        raise UnsupportedCacheRequestError(message) from None
    if value != value:  # noqa: PLR0124 (deliberate self-inequality check for NaN-like values)
        type_name = type(value).__name__
        message = (
            f"cannot canonicalize a non-reflexive value of type {type_name!r} "
            "for a cache key"
        )
        raise UnsupportedCacheRequestError(message)
    return value


def _legacy_order_sensitive_key(
    value: object, *, distinguish_numeric_subtypes: bool
) -> object:
    if (
        isinstance(value, tuple)
        and len(value) == _TAGGED_TUPLE_SIZE
        and any(value[0] is tag for tag in _ORDER_OWN_TAGS)
    ):
        return value
    if isinstance(value, Mapping):
        return (
            _ORDER_MAPPING_TAG,
            tuple(
                (
                    _legacy_order_sensitive_key(
                        key, distinguish_numeric_subtypes=distinguish_numeric_subtypes
                    ),
                    _legacy_order_sensitive_key(
                        item, distinguish_numeric_subtypes=distinguish_numeric_subtypes
                    ),
                )
                for key, item in value.items()
            ),
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return (
            _ORDER_SEQUENCE_TAG,
            tuple(
                _legacy_order_sensitive_key(
                    item, distinguish_numeric_subtypes=distinguish_numeric_subtypes
                )
                for item in value
            ),
        )
    if distinguish_numeric_subtypes:
        if isinstance(value, Int64):
            return (_ORDER_INT64_TAG, value)
        if isinstance(value, float):
            return (_ORDER_FLOAT_TAG, value)
    elif isinstance(value, Decimal128):
        return value.to_decimal()
    return value


def legacy_order_sensitive_key(value: object) -> object:
    return _legacy_order_sensitive_key(value, distinguish_numeric_subtypes=False)


def legacy_order_sensitive_discriminator_key(value: object) -> object:
    return _legacy_order_sensitive_key(value, distinguish_numeric_subtypes=True)


def legacy_find_filter_key(filter_document: object) -> object:
    if type(filter_document) is dict and all(
        type(field) is str
        and not field.startswith("$")
        and (value is None or type(value) in _SCALAR_TYPES)
        for field, value in filter_document.items()
    ):
        return (
            _SCALAR_PREDICATES,
            legacy_order_sensitive_discriminator_key(
                dict(sorted(filter_document.items()))
            ),
        )
    return legacy_order_sensitive_discriminator_key(filter_document)
