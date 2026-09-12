from __future__ import annotations

import bson

_ENVELOPE_FIELD = "v"


def encode_value(value: object) -> bytes:
    return bson.encode({_ENVELOPE_FIELD: value})


def decode_value(encoded: bytes) -> object:
    return bson.decode(encoded)[_ENVELOPE_FIELD]
