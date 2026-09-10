from __future__ import annotations

import bson

_ENVELOPE_FIELD = "v"


def encode_value(value: object) -> bytes:
    return bson.encode({_ENVELOPE_FIELD: value})


def decode_value(data: bytes) -> object:
    return bson.decode(data)[_ENVELOPE_FIELD]
