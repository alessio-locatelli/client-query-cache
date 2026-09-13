from __future__ import annotations

from collections.abc import Mapping, Sequence


def order_sensitive_key(value: object) -> object:
    if isinstance(value, Mapping):
        return tuple(
            (order_sensitive_key(key), order_sensitive_key(item))
            for key, item in value.items()
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(order_sensitive_key(item) for item in value)
    return value
