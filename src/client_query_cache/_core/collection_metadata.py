from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from client_query_cache._core.collation import normalize_collation

if TYPE_CHECKING:
    from collections.abc import Mapping

    from client_query_cache._core.keys import NamespaceId


@dataclass(frozen=True, slots=True)
class CollectionMetadata:
    checked_epoch: int
    is_cacheable: bool
    default_collation: Mapping[str, Any] | None


class CollectionMetadataCache:
    __slots__ = ("_entries", "_lock")

    def __init__(self) -> None:
        self._entries: dict[NamespaceId, CollectionMetadata] = {}
        self._lock = threading.Lock()

    def get(self, namespace: NamespaceId) -> CollectionMetadata | None:
        with self._lock:
            try:
                return self._entries[namespace]
            except KeyError:
                return None

    def put(self, namespace: NamespaceId, metadata: CollectionMetadata) -> None:
        with self._lock:
            self._entries[namespace] = metadata


@dataclass(frozen=True, slots=True)
class CollectionProbeResult:
    is_cacheable: bool
    default_collation: Mapping[str, Any] | None


def interpret_list_collections_entry(
    entry: Mapping[str, Any] | None,
) -> CollectionProbeResult | None:
    if entry is None:
        return None
    collection_type = entry["type"]
    try:
        options = entry["options"]
    except KeyError:
        options = {}
    try:
        collation = options["collation"]
    except KeyError:
        collation = None
    default_collation = normalize_collation(collation)
    return CollectionProbeResult(
        is_cacheable=collection_type == "collection",
        default_collation=default_collation,
    )
