from typing import TYPE_CHECKING

from ._core.errors import (
    CacheClosedError,
    CacheConfigurationError,
    CacheError,
    UnsupportedCacheRequestError,
)
from .shared import (
    SharedBypassReason,
    SharedBypassReasonCount,
    SharedCacheConfig,
    SharedCacheConnection,
    SharedCacheServer,
    SharedCacheStatistics,
    SharedCapacityUsage,
    SharedDatabaseHealth,
    SharedOwnerSnapshot,
    SharedStreamStatus,
)
from .synchronous import (
    BypassReason,
    BypassReasonCount,
    CacheCore,
    CacheCoreConfig,
    CachedCollection,
    CachedDatabase,
    CacheManager,
    CacheSnapshot,
    RetentionDeclineCount,
    RetentionDeclineReason,
    RetentionRecordKind,
    SelectiveInvalidation,
    StreamCostSnapshot,
    StreamHealthSnapshot,
    StreamHealthStatus,
)

if TYPE_CHECKING:
    from .synchronous import SharedCachedCollection, SharedCacheManager

__all__ = [
    "BypassReason",
    "BypassReasonCount",
    "CacheClosedError",
    "CacheConfigurationError",
    "CacheCore",
    "CacheCoreConfig",
    "CacheError",
    "CacheManager",
    "CacheSnapshot",
    "CachedCollection",
    "CachedDatabase",
    "RetentionDeclineCount",
    "RetentionDeclineReason",
    "RetentionRecordKind",
    "SelectiveInvalidation",
    "SharedBypassReason",
    "SharedBypassReasonCount",
    "SharedCacheConfig",
    "SharedCacheConnection",
    "SharedCacheManager",
    "SharedCacheServer",
    "SharedCacheStatistics",
    "SharedCachedCollection",
    "SharedCapacityUsage",
    "SharedDatabaseHealth",
    "SharedOwnerSnapshot",
    "SharedStreamStatus",
    "StreamCostSnapshot",
    "StreamHealthSnapshot",
    "StreamHealthStatus",
    "UnsupportedCacheRequestError",
]


def __getattr__(name: str) -> object:
    if name in {"SharedCacheManager", "SharedCachedCollection"}:
        from . import synchronous  # noqa: PLC0415 - The owner does not use worker adapters.

        globals().update(
            SharedCacheManager=synchronous.SharedCacheManager,
            SharedCachedCollection=synchronous.SharedCachedCollection,
        )
        return globals()[name]
    raise AttributeError(name)


def __dir__() -> list[str]:
    return sorted(set(globals()).union(__all__))
