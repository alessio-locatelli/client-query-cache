from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from client_query_cache._core.collation import normalize_collation
from client_query_cache._core.snapshots import BypassReason

if TYPE_CHECKING:
    from collections.abc import Mapping

    from client_query_cache._core.keys import NamespaceId


_COLLECTION_REASONS = {
    "collection": None,
    "view": BypassReason.VIEW_COLLECTION,
    "timeseries": BypassReason.TIME_SERIES_COLLECTION,
}


@dataclass(frozen=True, slots=True)
class CollectionMetadata:
    checked_epoch: int
    bypass_reason: BypassReason | None
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
    bypass_reason: BypassReason | None
    default_collation: Mapping[str, Any] | None

    @property
    def is_cacheable(self) -> bool:
        return self.bypass_reason is None


def interpret_list_collections_entry(
    entry: Mapping[str, Any] | None,
) -> CollectionProbeResult:
    if entry is None:
        return CollectionProbeResult(BypassReason.MISSING_COLLECTION, None)
    collection_type = entry["type"]
    try:
        bypass_reason = _COLLECTION_REASONS[collection_type]
    except KeyError:
        bypass_reason = BypassReason.METADATA_UNAVAILABLE
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
        bypass_reason=bypass_reason,
        default_collation=default_collation,
    )
