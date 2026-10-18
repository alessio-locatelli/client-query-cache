from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from client_query_cache._core.collation import normalize_collation
from client_query_cache._core.namespace_metadata import NamespaceMetadataCache
from client_query_cache._core.snapshots import BypassReason
from client_query_cache._types import NonNegativeFloat, NonNegativeInt, PositiveInt

if TYPE_CHECKING:
    from collections.abc import Mapping


_COLLECTION_REASONS = {
    "collection": None,
    "view": BypassReason.VIEW_COLLECTION,
    "timeseries": BypassReason.TIME_SERIES_COLLECTION,
}


@dataclass(frozen=True, slots=True)
class CollectionMetadata:
    checked_epoch: NonNegativeInt
    bypass_reason: BypassReason | None
    default_collation: Mapping[str, Any] | None
    epoch_bound: bool = True
    expires_at: NonNegativeFloat | None = None


class CollectionMetadataCache(NamespaceMetadataCache[CollectionMetadata]):
    __slots__ = ()

    def __init__(self, max_namespaces: PositiveInt = 1024) -> None:
        super().__init__(max_namespaces)


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
