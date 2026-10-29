from __future__ import annotations

import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from bson.errors import BSONError
from bson.regex import Regex

from client_query_cache._core.canonical import Canonical, canonicalize
from client_query_cache._core.codec import decode_value, encode_value
from client_query_cache._core.errors import UnsupportedCacheRequestError
from client_query_cache._core.order_sensitive_keys import order_sensitive_key

if TYPE_CHECKING:
    from bson.codec_options import CodecOptions

_ID_FIELD = "_id"
_EMPTY_REMAINDER: Mapping[str, Any] = MappingProxyType({})
_INT32_MIN = -(1 << 31)
_INT32_LIMIT = 1 << 31
_SCALAR_EQUALITY_TYPES = (int, str, bytes, bool, float)


class _NoIdentity:
    __slots__ = ()


NO_IDENTITY = _NoIdentity()


def _is_query_operator_mapping(value: Mapping[str, Any]) -> bool:
    return any(key.startswith("$") for key in value)


def _is_regex(value: object) -> bool:
    return isinstance(value, re.Pattern | Regex)


def extract_equality_value(value: object) -> object:
    if value is None:
        return NO_IDENTITY
    if type(value) in _SCALAR_EQUALITY_TYPES:
        return value
    if isinstance(value, Mapping) and _is_query_operator_mapping(value):
        return NO_IDENTITY
    if _is_regex(value):
        return NO_IDENTITY
    return value


def extract_id_anchor(filter_query: object) -> tuple[object, Mapping[str, Any]]:
    if type(filter_query) is not dict and not isinstance(filter_query, Mapping):
        return extract_equality_value(filter_query), _EMPTY_REMAINDER
    try:
        identity = extract_equality_value(filter_query[_ID_FIELD])
    except KeyError:
        return NO_IDENTITY, _EMPTY_REMAINDER
    if identity is NO_IDENTITY:
        return NO_IDENTITY, _EMPTY_REMAINDER
    if len(filter_query) == 1:
        return identity, _EMPTY_REMAINDER
    return identity, {
        key: value for key, value in filter_query.items() if key != _ID_FIELD
    }


def prepare_resolved_identity(identity: object) -> Canonical | None:
    if identity is None:
        return None
    try:
        canonical = canonicalize(identity)
        if canonical is identity or isinstance(identity, bool):
            return canonical
        return canonicalize(order_sensitive_key(identity))
    except UnsupportedCacheRequestError:
        return None


def normalize_identity_for_cache_key(
    identity: object,
    read_codec_options: CodecOptions[Any],
    stream_codec_options: CodecOptions[Any],
) -> object:
    if (
        type(identity) is int
        and _INT32_MIN <= identity < _INT32_LIMIT
        and read_codec_options is stream_codec_options
        and stream_codec_options.document_class is dict
        # PyMongo's decoder map determines whether BSON can alter integer IDs.
        and not stream_codec_options.type_registry._decoder_map  # noqa: SLF001
    ):
        return identity
    try:
        encoded = encode_value(identity, read_codec_options)
        return decode_value(encoded, stream_codec_options)
    except BSONError:
        return identity
