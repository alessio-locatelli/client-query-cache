from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence

from mongo_client_cache._core.errors import UnsupportedCacheRequestError

type Canonical = Hashable


def canonicalize(value: object) -> Canonical:
    if isinstance(value, Mapping):
        return tuple(sorted((key, canonicalize(item)) for key, item in value.items()))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(canonicalize(item) for item in value)
    try:
        hash(value)
    except TypeError:
        type_name = type(value).__name__
        message = f"cannot canonicalize value of type {type_name!r} for a cache key"
        raise UnsupportedCacheRequestError(message) from None
    return value
