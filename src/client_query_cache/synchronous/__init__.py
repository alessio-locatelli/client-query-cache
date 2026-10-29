from typing import TYPE_CHECKING

from client_query_cache._core.manager import CacheCoreConfig
from client_query_cache._core.snapshots import (
    BypassReason,
    BypassReasonCount,
    CacheSnapshot,
    RetentionDeclineCount,
    RetentionDeclineReason,
    RetentionRecordKind,
)
from client_query_cache._core.stream_cost import StreamCostSnapshot
from client_query_cache._core.stream_health import (
    StreamHealthSnapshot,
    StreamHealthStatus,
)
from client_query_cache._shared_index import LocalCacheCore as CacheCore

from .collection import CachedCollection
from .database import CachedDatabase
from .manager import CacheManager
from .streams import ChangeStreamCoordinator, DatabaseStreamSupervisor

__all__ = [
    "BypassReason",
    "BypassReasonCount",
    "CacheCore",
    "CacheCoreConfig",
    "CacheManager",
    "CacheSnapshot",
    "CachedCollection",
    "CachedDatabase",
    "ChangeStreamCoordinator",
    "DatabaseStreamSupervisor",
    "RetentionDeclineCount",
    "RetentionDeclineReason",
    "RetentionRecordKind",
    "SharedCacheManager",
    "SharedCachedCollection",
    "StreamCostSnapshot",
    "StreamHealthSnapshot",
    "StreamHealthStatus",
]

if TYPE_CHECKING:
    from .shared import SharedCachedCollection, SharedCacheManager


def __getattr__(name: str) -> object:
    if name in {"SharedCacheManager", "SharedCachedCollection"}:
        from . import shared  # noqa: PLC0415 - Resolve shared exports after both adapter packages initialize.

        return getattr(shared, name)
    raise AttributeError(name)
