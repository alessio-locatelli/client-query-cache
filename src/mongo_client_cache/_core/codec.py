from __future__ import annotations

from typing import TYPE_CHECKING, Any

import bson
from bson.codec_options import CodecOptions

if TYPE_CHECKING:
    from collections.abc import Mapping

_ENVELOPE_FIELD = "v"


def encode_value(
    value: object, codec_options: CodecOptions[Mapping[str, Any]] | None = None
) -> bytes:
    return bson.encode(
        {_ENVELOPE_FIELD: value}, codec_options=codec_options or CodecOptions()
    )


def decode_value(
    encoded: bytes, codec_options: CodecOptions[Mapping[str, Any]] | None = None
) -> object:
    return bson.decode(encoded, codec_options=codec_options)[_ENVELOPE_FIELD]
