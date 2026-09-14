from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence

from mongo_client_cache._core.errors import UnsupportedCacheRequestError

type Canonical = Hashable


class _CanonicalTag:
    __slots__ = ("_name",)

    def __init__(self, name: str) -> None:
        self._name = name

    def __repr__(self) -> str:
        return f"<canonical:{self._name}>"


# Private object identities, not strings: a caller-supplied tuple can never
# forge one of these by coincidence (unlike a string literal such as "map"),
# so the idempotency check below can never collide with real input.
_MAPPING_TAG = _CanonicalTag("map")
_SEQUENCE_TAG = _CanonicalTag("seq")
_BOOL_TAG = _CanonicalTag("bool")
_OWN_TAGS = (_MAPPING_TAG, _SEQUENCE_TAG, _BOOL_TAG)
_TAGGED_TUPLE_SIZE = 2


def canonicalize(value: object) -> Canonical:
    # Idempotent: a value already produced by this function (e.g. returned by
    # resolve_alias for later reuse as a lookup_identity/begin_identity_admission
    # argument) must pass through unchanged, since a mapping/sequence/bool
    # identity would otherwise be wrapped a second time and stop matching the
    # key it was originally cached under. `_OWN_TAGS` is a plain tuple (not a
    # set) and compared with `is`-backed `==`, not `in` on a hashed
    # container, so an unhashable first element (e.g. a dict) can't raise
    # here.
    if (
        isinstance(value, tuple)
        and len(value) == _TAGGED_TUPLE_SIZE
        and any(value[0] is tag for tag in _OWN_TAGS)
    ):
        return value
    if isinstance(value, Mapping):
        pairs = [(canonicalize(key), canonicalize(item)) for key, item in value.items()]
        items = tuple(sorted(pairs, key=lambda pair: repr(pair[0])))
        return (_MAPPING_TAG, items)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return (_SEQUENCE_TAG, tuple(canonicalize(item) for item in value))
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
