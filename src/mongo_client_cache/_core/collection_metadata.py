from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

    from mongo_client_cache._core.keys import NamespaceId


@dataclass(frozen=True, slots=True)
class CollectionMetadata:
    checked_epoch: int
    is_view: bool
    default_collation: Mapping[str, Any] | None


class CollectionMetadataCache:
    __slots__ = ("_entries", "_lock")

    def __init__(self) -> None:
        self._entries: dict[NamespaceId, CollectionMetadata] = {}
        self._lock = threading.Lock()

    def get(self, namespace: NamespaceId) -> CollectionMetadata | None:
        with self._lock:
            return self._entries.get(namespace)

    def put(self, namespace: NamespaceId, metadata: CollectionMetadata) -> None:
        with self._lock:
            self._entries[namespace] = metadata


@dataclass(frozen=True, slots=True)
class CollectionProbeResult:
    is_view: bool
    default_collation: Mapping[str, Any] | None


def interpret_list_collections_entry(
    entry: Mapping[str, Any] | None,
) -> CollectionProbeResult:
    if entry is None:
        return CollectionProbeResult(is_view=False, default_collation=None)
    is_view = entry.get("type") == "view"
    default_collation = entry.get("options", {}).get("collation")
    return CollectionProbeResult(is_view=is_view, default_collation=default_collation)
