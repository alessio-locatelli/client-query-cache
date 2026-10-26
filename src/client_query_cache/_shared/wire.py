import datetime as dt
import re
import struct
from decimal import Decimal
from functools import cache
from typing import TYPE_CHECKING, Final
from uuid import UUID

import bson
from bson.codec_options import CodecOptions, DatetimeConversion
from bson.datetime_ms import DatetimeMS
from bson.dbref import DBRef
from bson.decimal128 import Decimal128
from bson.errors import BSONError
from bson.int64 import Int64
from bson.max_key import MaxKey
from bson.min_key import MinKey
from bson.objectid import ObjectId
from bson.timestamp import Timestamp

from client_query_cache._core import canonical as canonical_tags
from client_query_cache._core import count_reads as count_tags
from client_query_cache._core import order_sensitive_keys as order_tags
from client_query_cache._core import query_filters as filter_tags
from client_query_cache._core.codec import _TypeRegistryIdentity
from client_query_cache._shared_index import find_key_encoder
from client_query_cache._types import NonNegativeInt, PositiveInt

if TYPE_CHECKING:
    from collections.abc import Mapping

    from client_query_cache._shared_index import FindKeyEncoder

PROTOCOL_VERSION: Final = 1
_LENGTH = struct.Struct("<I")
LENGTH_BYTES: Final = _LENGTH.size
_WIRE_OPTIONS: CodecOptions[dict[str, object]] = CodecOptions(tz_aware=False)

_TAGS: Final[dict[str, object]] = {
    "canonical-map": canonical_tags._MAPPING_TAG,
    "canonical-seq": canonical_tags._SEQUENCE_TAG,
    "canonical-bool": canonical_tags._BOOL_TAG,
    "order-map": order_tags._MAPPING_TAG.canonical,
    "order-seq": order_tags._SEQUENCE_TAG.canonical,
    "order-float": order_tags._FLOAT_TAG.canonical,
    "order-int64": order_tags._INT64_TAG.canonical,
    "filter-scalar-predicates": filter_tags._SCALAR_PREDICATES.canonical,
    "count-omitted": count_tags._OMITTED,
}
_TAG_NAMES: Final = {id(tag): name for name, tag in _TAGS.items()}
_CLASSES: Final[dict[str, type]] = {"dict": dict}
_CLASS_NAMES: Final = {id(kind): name for name, kind in _CLASSES.items()}
_REGEX_KEY_FLAGS_MASK: Final = ~int(re.DEBUG)
_EMPTY_REGISTRY: Final = "empty-registry"
_UTC: Final = "utc"
_MAX_CACHED_KEY_BYTES: Final = 4096
_INT64_MIN: Final = -(1 << 63)
_INT64_LIMIT: Final = 1 << 63
_INT64: Final = struct.Struct("<q")
# The outer key document and inner tagged node each end with a BSON terminator.
_INT_KEY_SUFFIX: Final = b"\x00\x00"
_INT_KEY_TRAILER_BYTES: Final = _INT64.size + len(_INT_KEY_SUFFIX)
_INT_KEY_PREFIX: Final = bson.encode({"k": {"t": "int", "p": Int64(0)}})[
    :-_INT_KEY_TRAILER_BYTES
]
_INT_KEY_VALUE_OFFSET: Final = len(_INT_KEY_PREFIX)
_INT_KEY_BYTES: Final = _INT_KEY_VALUE_OFFSET + _INT_KEY_TRAILER_BYTES


class UnportableKeyError(ValueError):
    pass


class ProtocolError(ValueError):
    pass


def _registry_is_empty(identity: _TypeRegistryIdentity) -> bool:
    registry = identity._registry
    return not registry.codecs and registry.fallback_encoder is None


def to_wire(value: object) -> object:
    if isinstance(value, tuple):
        return {"t": "tuple", "p": [to_wire(item) for item in value]}
    if id(value) in _TAG_NAMES:
        return {"t": "tag", "p": _TAG_NAMES[id(value)]}
    if value is None or isinstance(
        value,
        (bool, str, bytes, ObjectId, Decimal128, Timestamp, MinKey, MaxKey, DBRef),
    ):
        return value
    if isinstance(value, Int64):
        return {"t": "int64", "p": value}
    if isinstance(value, int):
        if isinstance(value, DatetimeConversion):
            return {"t": "datetime-conversion", "p": int(value)}
        if not _INT64_MIN <= value < _INT64_LIMIT:
            message = "integer outside the BSON int64 range"
            raise UnportableKeyError(message)
        return {"t": "int", "p": Int64(value)}
    if isinstance(value, float):
        return value
    if isinstance(value, re.Pattern):
        return {"t": "regex", "p": [value.pattern, value.flags & _REGEX_KEY_FLAGS_MASK]}
    if isinstance(value, UUID):
        return {"t": "uuid", "p": value.bytes}
    if isinstance(value, DatetimeMS):
        return {"t": "datetime-ms", "p": Int64(int(value))}
    if isinstance(value, dt.datetime):
        if value.microsecond % 1000 or value.tzinfo is not None:
            return {"t": "datetime", "p": value.isoformat()}
        return value
    if isinstance(value, type) and id(value) in _CLASS_NAMES:
        return {"t": "class", "p": _CLASS_NAMES[id(value)]}
    if isinstance(value, _TypeRegistryIdentity) and _registry_is_empty(value):
        return {"t": "registry", "p": _EMPTY_REGISTRY}
    if isinstance(value, dt.tzinfo) and value is dt.UTC:
        return {"t": "tzinfo", "p": _UTC}
    if isinstance(value, Decimal):
        message = "native Decimal keys have no portable codec profile"
        raise UnportableKeyError(message)
    message = f"no portable representation for {type(value).__name__}"
    raise UnportableKeyError(message)


_EMPTY_IDENTITY: Final = _TypeRegistryIdentity(CodecOptions().type_registry)


def _integer(payload: object) -> int:
    if not isinstance(payload, int) or isinstance(payload, bool):
        raise ProtocolError("malformed integer node")
    return payload


def from_wire(value: object) -> object:
    if not isinstance(value, dict):
        return value
    try:
        tag, payload = value["t"], value["p"]
    except KeyError as error:
        raise ProtocolError("malformed canonical node") from error
    match tag:
        case "tuple":
            if not isinstance(payload, list):
                raise ProtocolError("malformed tuple node")
            return tuple(from_wire(item) for item in payload)
        case "int":
            return int(_integer(payload))
        case "int64":
            return Int64(_integer(payload))
        case "datetime-conversion":
            try:
                return DatetimeConversion(_integer(payload))
            except ValueError as error:
                raise ProtocolError("unknown datetime conversion") from error
        case "regex":
            if (
                not isinstance(payload, list)
                or len(payload) != 2
                or not isinstance(payload[0], (str, bytes))
            ):
                raise ProtocolError("malformed regex node")
            try:
                return re.compile(
                    payload[0], _integer(payload[1]) & _REGEX_KEY_FLAGS_MASK
                )
            except re.PatternError as error:
                raise ProtocolError("malformed regex pattern") from error
            except ValueError as error:
                raise ProtocolError("invalid regex flags") from error
            except OverflowError as error:
                raise ProtocolError("regex flags exceed the native range") from error
        case "uuid":
            if not isinstance(payload, bytes) or len(payload) != 16:
                raise ProtocolError("malformed UUID node")
            return UUID(bytes=payload)
        case "datetime-ms":
            return DatetimeMS(_integer(payload))
        case "datetime":
            if not isinstance(payload, str):
                raise ProtocolError("malformed datetime node")
            try:
                return dt.datetime.fromisoformat(payload)
            except ValueError as error:
                raise ProtocolError("invalid datetime key") from error
        case "class":
            try:
                return _CLASSES[str(payload)]
            except KeyError as error:
                raise ProtocolError("unknown document class") from error
        case "registry" if payload == _EMPTY_REGISTRY:
            return _EMPTY_IDENTITY
        case "tzinfo" if payload == _UTC:
            return dt.UTC
        case "tag":
            try:
                return _TAGS[str(payload)]
            except KeyError as error:
                raise ProtocolError("unknown canonical tag") from error
    raise ProtocolError("unknown canonical node")


def encode_key(value: object) -> bytes:
    if type(value) is int and _INT64_MIN <= value < _INT64_LIMIT:
        return _INT_KEY_PREFIX + _INT64.pack(value) + _INT_KEY_SUFFIX
    return bson.encode({"k": to_wire(value)})


def decode_key(encoded: object) -> object:
    if not isinstance(encoded, bytes):
        raise ProtocolError("cache keys must be encoded BSON")
    if (
        type(encoded) is bytes
        and len(encoded) == _INT_KEY_BYTES
        and encoded.startswith(_INT_KEY_PREFIX)
        and encoded.endswith(_INT_KEY_SUFFIX)
    ):
        return _INT64.unpack_from(encoded, _INT_KEY_VALUE_OFFSET)[0]
    try:
        document = bson.decode(encoded, codec_options=_WIRE_OPTIONS)
    except BSONError as error:
        raise ProtocolError("invalid cache key") from error
    try:
        node = document["k"]
    except KeyError as error:
        raise ProtocolError("cache key has no value") from error
    return from_wire(node)


@cache
def _find_encoder() -> FindKeyEncoder:
    return find_key_encoder(_TAG_NAMES)


class KeyCache:
    __slots__ = ("_decoded", "_encoded", "_finds", "_limit")

    def __init__(self, limit: PositiveInt) -> None:
        self._limit = limit
        self._encoded: dict[object, bytes] = {}
        self._finds: dict[object, tuple[bytes, bytes]] = {}
        self._decoded: dict[bytes, object] = {}

    def encode(self, value: object) -> bytes:
        try:
            return self._encoded[value]
        except KeyError:
            pass
        encoded = encode_key(value)
        if len(encoded) <= _MAX_CACHED_KEY_BYTES:
            if len(self._encoded) + len(self._finds) >= self._limit:
                self._encoded.clear()
                self._finds.clear()
            self._encoded[value] = encoded
        return encoded

    def find(self, family: object, limit: int) -> tuple[bytes, bytes]:
        if type(limit) is int:
            canonical_limit: object = limit
            cache_key: object = (family, limit)
        else:
            canonical_limit = canonical_tags.canonicalize(limit)
            # BSON Int64 compares equal to int but has a different wire key.
            cache_key = (family, type(limit), canonical_limit)
        try:
            return self._finds[cache_key]
        except KeyError:
            pass
        encoder = _find_encoder()
        try:
            family_bytes = self._encoded[family]
        except KeyError:
            encoded = encoder.encode(family, canonical_limit, encode_key)
            family_bytes, exact = encoded
            new_family = True
        else:
            exact = encoder.wrap(family_bytes, canonical_limit, encode_key)
            encoded = (family_bytes, exact)
            new_family = False
        if len(family_bytes) <= _MAX_CACHED_KEY_BYTES:
            retain_pair = self._limit >= 2 and len(exact) <= _MAX_CACHED_KEY_BYTES
            required = int(new_family) + int(retain_pair)
            if len(self._encoded) + len(self._finds) + required > self._limit:
                self._encoded.clear()
                self._finds.clear()
                new_family = True
            if new_family:
                self._encoded[family] = family_bytes
            if retain_pair:
                self._finds[cache_key] = encoded
        return encoded

    def decode(self, encoded: object) -> object:
        try:
            return self._decoded[encoded]  # type: ignore[index]
        except KeyError:
            pass
        except TypeError as error:
            raise ProtocolError("cache keys must be encoded BSON") from error
        value = decode_key(encoded)
        assert isinstance(encoded, bytes)
        if len(encoded) <= _MAX_CACHED_KEY_BYTES:
            if len(self._decoded) >= self._limit:
                self._decoded.clear()
            self._decoded[encoded] = value
        return value


def encode_frame(message: Mapping[str, object]) -> bytes:
    body = bson.encode(message)
    return _LENGTH.pack(len(body)) + body


def frame_length(header: bytes, limit: PositiveInt) -> NonNegativeInt:
    length: int = _LENGTH.unpack(header)[0]
    if length > limit:
        raise ProtocolError("frame exceeds the registered limit")
    return length


def decode_queued_frame(frame: bytes, limit: PositiveInt) -> dict[str, object]:
    frame_bytes = len(frame)
    if frame_bytes < LENGTH_BYTES:
        raise ProtocolError("queued frame has no length header")
    body_bytes = frame_length(frame[:LENGTH_BYTES], limit)
    if frame_bytes != LENGTH_BYTES + body_bytes:
        raise ProtocolError("queued frame length differs from its header")
    return decode_frame(frame[LENGTH_BYTES:])


def decode_frame(body: bytes | memoryview) -> dict[str, object]:
    try:
        message = bson.decode(body, codec_options=_WIRE_OPTIONS)
    except BSONError as error:
        raise ProtocolError("invalid BSON frame") from error
    try:
        version = message["v"]
    except KeyError as error:
        raise ProtocolError("frame has no protocol version") from error
    if version != PROTOCOL_VERSION:
        raise ProtocolError("unsupported protocol version")
    return message
