from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence

from client_query_cache._core.errors import UnsupportedCacheRequestError

type Canonical = Hashable


class _CanonicalTag:
    __slots__ = ("_name",)

    def __init__(self, name: str) -> None:
        self._name = name

    def __repr__(self) -> str:
        return f"<canonical:{self._name}>"


class _PendingTag:
    __slots__ = ("canonical", "items")

    def __init__(self, name: str, *, items: bool) -> None:
        self.canonical = _CanonicalTag(name)
        self.items = items


_MAPPING_TAG = _CanonicalTag("map")
_SEQUENCE_TAG = _CanonicalTag("seq")
_BOOL_TAG = _CanonicalTag("bool")
_TAGGED_TUPLE_SIZE = 2


def canonicalize(value: object) -> Canonical:
    value_type = type(value)
    if value_type is int or value_type is str or value_type is bytes or value is None:
        return value
    if isinstance(value, tuple) and len(value) == _TAGGED_TUPLE_SIZE:
        tag, payload = value
        if type(tag) is _CanonicalTag:
            return value
        if type(tag) is _PendingTag:
            if tag.items:
                return (tag.canonical, tuple([canonicalize(item) for item in payload]))
            return (tag.canonical, canonicalize(payload))
    if isinstance(value, Mapping):
        pairs = [(canonicalize(key), canonicalize(item)) for key, item in value.items()]
        items = tuple(sorted(pairs, key=lambda pair: repr(pair[0])))
        return (_MAPPING_TAG, items)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return (_SEQUENCE_TAG, tuple([canonicalize(item) for item in value]))
    if isinstance(value, bool):
        return (_BOOL_TAG, value)
    try:
        hash(value)
    except TypeError:
        type_name = type(value).__name__
        message = f"cannot canonicalize value of type {type_name!r} for a cache key"
        raise UnsupportedCacheRequestError(message) from None
    if value != value:  # noqa: PLR0124 (deliberate self-inequality check for NaN-like values)
        type_name = type(value).__name__
        message = (
            f"cannot canonicalize a non-reflexive value of type {type_name!r} "
            "for a cache key"
        )
        raise UnsupportedCacheRequestError(message)
    return value


def is_canonicalizable(value: object) -> bool:
    try:
        canonicalize(value)
    except UnsupportedCacheRequestError:
        return False
    return True
