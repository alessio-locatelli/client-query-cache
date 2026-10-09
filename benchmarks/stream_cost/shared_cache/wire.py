# Research prototype: canonical tags are private core objects.
# ruff: noqa: SLF001

import datetime
import struct
from decimal import Decimal
from typing import TYPE_CHECKING, Final

import bson
from bson.codec_options import CodecOptions, DatetimeConversion
from bson.decimal128 import Decimal128
from bson.errors import BSONError
from bson.int64 import Int64
from bson.objectid import ObjectId

from client_query_cache._core import canonical as canonical_tags
from client_query_cache._core import order_sensitive_keys as order_tags
from client_query_cache._core import query_filters as filter_tags
from client_query_cache._core.codec import _TypeRegistryIdentity
from client_query_cache._types import NonNegativeInt, PositiveInt

if TYPE_CHECKING:
    from collections.abc import Mapping

PROTOCOL_VERSION: Final = 1
_LENGTH = struct.Struct("<I")
LENGTH_BYTES: Final = _LENGTH.size
_WIRE_OPTIONS: CodecOptions[dict[str, object]] = CodecOptions(tz_aware=False)

_TAGS: Final[dict[str, object]] = {
    "canonical-map": canonical_tags._MAPPING_TAG,
    "canonical-seq": canonical_tags._SEQUENCE_TAG,
    "canonical-bool": canonical_tags._BOOL_TAG,
    "order-map": order_tags._MAPPING_TAG,
    "order-seq": order_tags._SEQUENCE_TAG,
    "order-float": order_tags._FLOAT_TAG,
    "order-int64": order_tags._INT64_TAG,
    "filter-scalar-predicates": filter_tags._SCALAR_PREDICATES,
}
_TAG_NAMES: Final = {id(tag): name for name, tag in _TAGS.items()}
_CLASSES: Final[dict[str, type]] = {"dict": dict}
_CLASS_NAMES: Final = {id(kind): name for name, kind in _CLASSES.items()}
_EMPTY_REGISTRY: Final = "empty-registry"
_UTC: Final = "utc"


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
    if value is None or isinstance(value, (bool, str, bytes, ObjectId, Decimal128)):
        return value
    if isinstance(value, Int64):
        return {"t": "int64", "p": value}
    if isinstance(value, int):
        if isinstance(value, DatetimeConversion):
            return {"t": "datetime-conversion", "p": int(value)}
        if not -(2**63) <= value < 2**63:
            message = "integer outside the BSON int64 range"
            raise UnportableKeyError(message)
        return {"t": "int", "p": Int64(value)}
    if isinstance(value, float):
        return value
    if isinstance(value, datetime.datetime):
        if value.microsecond % 1000 or value.tzinfo is not None:
            message = "datetime key requires naive millisecond precision"
            raise UnportableKeyError(message)
        return value
    if isinstance(value, type) and id(value) in _CLASS_NAMES:
        return {"t": "class", "p": _CLASS_NAMES[id(value)]}
    if isinstance(value, _TypeRegistryIdentity) and _registry_is_empty(value):
        return {"t": "registry", "p": _EMPTY_REGISTRY}
    if isinstance(value, datetime.tzinfo) and value is datetime.UTC:
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
        case "class":
            try:
                return _CLASSES[str(payload)]
            except KeyError as error:
                raise ProtocolError("unknown document class") from error
        case "registry" if payload == _EMPTY_REGISTRY:
            return _EMPTY_IDENTITY
        case "tzinfo" if payload == _UTC:
            return datetime.UTC
        case "tag":
            try:
                return _TAGS[str(payload)]
            except KeyError as error:
                raise ProtocolError("unknown canonical tag") from error
    raise ProtocolError("unknown canonical node")


def encode_key(value: object) -> bytes:
    return bson.encode({"k": to_wire(value)})


def decode_key(encoded: object) -> object:
    if not isinstance(encoded, bytes):
        raise ProtocolError("cache keys must be encoded BSON")
    try:
        document = bson.decode(encoded, codec_options=_WIRE_OPTIONS)
    except BSONError as error:
        raise ProtocolError("invalid cache key") from error
    try:
        node = document["k"]
    except KeyError as error:
        raise ProtocolError("cache key has no value") from error
    return from_wire(node)


class KeyCache:
    __slots__ = ("_decoded", "_encoded", "_limit")

    def __init__(self, limit: PositiveInt) -> None:
        self._limit = limit
        self._encoded: dict[object, bytes] = {}
        self._decoded: dict[bytes, object] = {}

    def encode(self, value: object) -> bytes:
        try:
            return self._encoded[value]
        except KeyError:
            pass
        encoded = encode_key(value)
        if len(self._encoded) >= self._limit:
            self._encoded.clear()
        self._encoded[value] = encoded
        return encoded

    def decode(self, encoded: object) -> object:
        try:
            return self._decoded[encoded]  # type: ignore[index]
        except KeyError:
            pass
        except TypeError as error:
            raise ProtocolError("cache keys must be encoded BSON") from error
        value = decode_key(encoded)
        if len(self._decoded) >= self._limit:
            self._decoded.clear()
        self._decoded[encoded] = value  # type: ignore[index]
        return value


def encode_frame(message: Mapping[str, object]) -> bytes:
    body = bson.encode(message)
    return _LENGTH.pack(len(body)) + body


def frame_length(header: bytes, limit: PositiveInt) -> NonNegativeInt:
    length: int = _LENGTH.unpack(header)[0]
    if length > limit:
        raise ProtocolError("frame exceeds the registered limit")
    return length


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
