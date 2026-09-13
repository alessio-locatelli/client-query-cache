from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from bson.errors import BSONError

from mongo_client_cache._core.codec import decode_value, encode_value

if TYPE_CHECKING:
    from bson.codec_options import CodecOptions

_ID_FIELD = "_id"


class _NoIdentity:
    __slots__ = ()


NO_IDENTITY = _NoIdentity()


def _is_query_operator_mapping(value: Mapping[str, Any]) -> bool:
    return any(key.startswith("$") for key in value)


def extract_id_identity(filter_query: object) -> object:
    if filter_query is None:
        return NO_IDENTITY
    if not isinstance(filter_query, Mapping):
        return filter_query
    if set(filter_query) != {_ID_FIELD}:
        return NO_IDENTITY
    value = filter_query[_ID_FIELD]
    if value is None:
        return NO_IDENTITY
    if isinstance(value, Mapping) and _is_query_operator_mapping(value):
        return NO_IDENTITY
    return value


def normalize_identity_for_cache_key(
    identity: object,
    read_codec_options: CodecOptions[Any],
    stream_codec_options: CodecOptions[Any],
) -> object:
    try:
        encoded = encode_value(identity, read_codec_options)
        return decode_value(encoded, stream_codec_options)
    except BSONError:
        return identity
