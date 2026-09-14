from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mongo_client_cache._core.identity_reads import NO_IDENTITY, extract_equality_value

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mongo_client_cache._core.keys import NamespaceId


@dataclass(frozen=True, slots=True)
class UniqueKeyDefinition:
    fields: tuple[str, ...]
    collation: Mapping[str, Any] | None


def _is_eligible_index(index_spec: Mapping[str, Any]) -> bool:
    if not index_spec.get("unique", False):
        return False
    if "partialFilterExpression" in index_spec:
        return False
    if index_spec.get("sparse", False):
        return False
    return not any(value == "hashed" for value in index_spec.get("key", {}).values())


def discover_unique_keys(
    index_specs: Sequence[Mapping[str, Any]],
) -> tuple[UniqueKeyDefinition, ...]:
    return tuple(
        UniqueKeyDefinition(
            fields=tuple(index_spec["key"]), collation=index_spec.get("collation")
        )
        for index_spec in index_specs
        if _is_eligible_index(index_spec)
    )


def _extract_ordered_values(
    filter_query: Mapping[str, Any], fields: tuple[str, ...]
) -> tuple[Any, ...] | None:
    values: list[Any] = []
    for field in fields:
        value = extract_equality_value(filter_query[field])
        if value is NO_IDENTITY:
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
            return self._entries.get(namespace)

    def put(self, namespace: NamespaceId, metadata: UniqueKeyMetadata) -> None:
        with self._lock:
            self._entries[namespace] = metadata
