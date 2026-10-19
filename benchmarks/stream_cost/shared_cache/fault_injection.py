from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from pymongo.errors import OperationFailure

from client_query_cache._types import BsonDict, NonEmptyStr

if TYPE_CHECKING:
    from collections.abc import Mapping

    from client_query_cache.asynchronous.manager import (
        CacheManager as AsyncCacheManager,
    )
    from client_query_cache.asynchronous.streams import (
        DatabaseStreamSupervisor as AsyncDatabaseStreamSupervisor,
    )
    from client_query_cache.synchronous.manager import CacheManager
    from client_query_cache.synchronous.streams import (
        DatabaseStreamSupervisor as SyncDatabaseStreamSupervisor,
    )

_HISTORY_LOST = 286


def lose_sync_stream_history(supervisor: SyncDatabaseStreamSupervisor) -> None:
    supervisor_type = type(supervisor)
    original = supervisor_type._open_stream

    def unresumable(
        _instance: SyncDatabaseStreamSupervisor,
        *,
        resume_token: Mapping[str, object] | None,  # noqa: ARG001 - Preserve the patched method's keyword signature.
        use_start_after: bool,  # noqa: ARG001 - Preserve the patched method's keyword signature.
    ) -> None:
        supervisor_type._open_stream = original  # type: ignore[method-assign]
        raise OperationFailure("history lost", code=_HISTORY_LOST)

    supervisor_type._open_stream = unresumable  # type: ignore[method-assign,assignment]
    stream = supervisor._stream
    assert stream is not None
    stream.close()


async def lose_async_stream_history(
    supervisor: AsyncDatabaseStreamSupervisor,
) -> None:
    supervisor_type = type(supervisor)
    original = supervisor_type._open_stream

    async def unresumable(
        _instance: AsyncDatabaseStreamSupervisor,
        *,
        resume_token: Mapping[str, object] | None,  # noqa: ARG001 - Preserve the patched method's keyword signature.
        use_start_after: bool,  # noqa: ARG001 - Preserve the patched method's keyword signature.
    ) -> None:
        supervisor_type._open_stream = original  # type: ignore[method-assign]
        await asyncio.sleep(0)
        raise OperationFailure("history lost", code=_HISTORY_LOST)

    supervisor_type._open_stream = unresumable  # type: ignore[method-assign,assignment]
    stream = supervisor._stream
    assert stream is not None
    await stream.close()


def independent_sync_supervisor(
    manager: CacheManager[BsonDict], database: NonEmptyStr
) -> SyncDatabaseStreamSupervisor:
    return manager._coordinator._supervisors[database]


def independent_async_supervisor(
    manager: AsyncCacheManager[BsonDict], database: NonEmptyStr
) -> AsyncDatabaseStreamSupervisor:
    return manager._coordinator._supervisors[database]
