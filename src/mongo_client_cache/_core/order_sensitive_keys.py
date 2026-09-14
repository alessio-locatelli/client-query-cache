from __future__ import annotations

from collections.abc import Mapping, Sequence


class _OrderTag:
    __slots__ = ()


_MAPPING_TAG = _OrderTag()
_SEQUENCE_TAG = _OrderTag()


def order_sensitive_key(value: object) -> object:
    if isinstance(value, Mapping):
        return (
            _MAPPING_TAG,
            tuple(
                (order_sensitive_key(key), order_sensitive_key(item))
                for key, item in value.items()
            ),
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return (_SEQUENCE_TAG, tuple(order_sensitive_key(item) for item in value))
    return value
