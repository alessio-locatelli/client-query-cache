from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from client_query_cache._core.canonical import is_canonicalizable
from client_query_cache._core.collation import normalize_collation
from client_query_cache._core.identity_reads import NO_IDENTITY, extract_equality_value

if TYPE_CHECKING:
    from client_query_cache._core.keys import NamespaceId


@dataclass(frozen=True, slots=True)
class UniqueKeyDefinition:
    fields: tuple[str, ...]
    collation: Mapping[str, Any] | None


def _is_eligible_index(index_spec: Mapping[str, Any]) -> bool:
    try:
        is_unique = index_spec["unique"]
    except KeyError:
        is_unique = False
    if not is_unique:
        return False
    if "partialFilterExpression" in index_spec:
        return False
    try:
        is_sparse = index_spec["sparse"]
    except KeyError:
        is_sparse = False
    if is_sparse:
        return False
    return not any(value == "hashed" for value in index_spec["key"].values())


def discover_unique_keys(
    index_specs: Sequence[Mapping[str, Any]],
) -> tuple[UniqueKeyDefinition, ...]:
    unique_keys = []
    for index_spec in index_specs:
        if not _is_eligible_index(index_spec):
            continue
        try:
            collation = index_spec["collation"]
        except KeyError:
            collation = None
        unique_keys.append(
            UniqueKeyDefinition(
                fields=tuple(index_spec["key"]),
                collation=normalize_collation(collation),
            )
        )
    return tuple(unique_keys)


def _extract_ordered_values(
    filter_query: Mapping[str, Any], fields: tuple[str, ...]
) -> tuple[Any, ...] | None:
    values: list[Any] = []
    for field in fields:
        value = extract_equality_value(filter_query[field])
        if value is NO_IDENTITY or not is_canonicalizable(value):
            return None
        if (
            isinstance(value, Sequence)
            and not isinstance(value, (str, bytes, bytearray))
            and not value
        ):
            return None
        values.append(value)
    return tuple(values)


def match_unique_key(
    filter_query: object,
    keys: Sequence[UniqueKeyDefinition],
    effective_collation: Mapping[str, Any] | None,
) -> tuple[UniqueKeyDefinition, tuple[Any, ...]] | None:
    if not isinstance(filter_query, Mapping):
        return None
    filter_fields = set(filter_query)
    for key in keys:
        if key.collation != effective_collation:
            continue
        if filter_fields != set(key.fields):
            continue
        values = _extract_ordered_values(filter_query, key.fields)
        if values is not None:
            return key, values
    return None


@dataclass(frozen=True, slots=True)
class UniqueKeyMetadata:
    checked_index_generation: int
    keys: tuple[UniqueKeyDefinition, ...]


class UniqueKeyMetadataCache:
    __slots__ = ("_entries", "_lock")

    def __init__(self) -> None:
        self._entries: dict[NamespaceId, UniqueKeyMetadata] = {}
        self._lock = threading.Lock()

    def get(self, namespace: NamespaceId) -> UniqueKeyMetadata | None:
        with self._lock:
            try:
                return self._entries[namespace]
            except KeyError:
                return None

    def put(self, namespace: NamespaceId, metadata: UniqueKeyMetadata) -> None:
        with self._lock:
            self._entries[namespace] = metadata
