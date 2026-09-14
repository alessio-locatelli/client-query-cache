from __future__ import annotations

from collections.abc import Mapping, Sequence


class _OrderTag:
    __slots__ = ()


_MAPPING_TAG = _OrderTag()
_SEQUENCE_TAG = _OrderTag()
_FLOAT_TAG = _OrderTag()


def _order_sensitive_key(value: object, *, distinguish_float: bool) -> object:
    if isinstance(value, Mapping):
        return (
            _MAPPING_TAG,
            tuple(
                (
                    _order_sensitive_key(key, distinguish_float=distinguish_float),
                    _order_sensitive_key(item, distinguish_float=distinguish_float),
                )
                for key, item in value.items()
            ),
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return (
            _SEQUENCE_TAG,
            tuple(
                _order_sensitive_key(item, distinguish_float=distinguish_float)
                for item in value
            ),
        )
    if distinguish_float and isinstance(value, float):
        return (_FLOAT_TAG, value)
    return value


def order_sensitive_key(value: object) -> object:
    return _order_sensitive_key(value, distinguish_float=False)


def order_sensitive_discriminator_key(value: object) -> object:
    return _order_sensitive_key(value, distinguish_float=True)
