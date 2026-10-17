from __future__ import annotations

from typing import TYPE_CHECKING, Any

import bson
from bson.codec_options import CodecOptions

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bson.codec_options import TypeRegistry

_ENVELOPE_FIELD = "v"
# BSON length, document tag, UTF-8 field name, and its NUL terminator.
_DOCUMENT_OFFSET = 4 + 1 + len(_ENVELOPE_FIELD.encode()) + 1


class _TypeRegistryIdentity:
    __slots__ = ("_registry",)

    def __init__(self, registry: TypeRegistry) -> None:
        self._registry = registry

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, _TypeRegistryIdentity)
            and self._registry is other._registry
        )

    def __hash__(self) -> int:
        return id(self._registry)


def encode_value(
    value: object, codec_options: CodecOptions[Mapping[str, Any]] | None = None
) -> bytes:
    return bson.encode(
        {_ENVELOPE_FIELD: value}, codec_options=codec_options or CodecOptions()
    )


def encode_document(
    document: Mapping[str, Any], codec_options: CodecOptions[Mapping[str, Any]]
) -> bytes:
    # Embedded encoding preserves field order; top-level encoding promotes _id.
    return encode_value(document, codec_options)[_DOCUMENT_OFFSET:-1]


def decode_value(
    encoded: bytes, codec_options: CodecOptions[Mapping[str, Any]] | None = None
) -> object:
    return bson.decode(encoded, codec_options=codec_options)[_ENVELOPE_FIELD]


def codec_fingerprint(codec_options: CodecOptions[Mapping[str, Any]]) -> object:
    return (
        codec_options.document_class,
        codec_options.tz_aware,
        codec_options.uuid_representation,
        codec_options.unicode_decode_error_handler,
        codec_options.tzinfo,
        codec_options.datetime_conversion,
        _TypeRegistryIdentity(codec_options.type_registry),
    )
