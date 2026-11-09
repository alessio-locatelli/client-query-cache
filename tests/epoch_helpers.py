from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from client_query_cache._core.contracts import LocalCacheCore
    from client_query_cache._core.keys import NamespaceId
    from client_query_cache._types import NonNegativeInt


def current_epoch(core: LocalCacheCore, namespace: NamespaceId) -> NonNegativeInt:
    epoch = core.try_current_epoch(namespace)
    assert epoch is not None
    return epoch
