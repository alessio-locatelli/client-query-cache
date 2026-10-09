from __future__ import annotations

import gc
from collections.abc import Awaitable, Mapping
from typing import TYPE_CHECKING, Any

from pymongo.asynchronous.command_cursor import AsyncCommandCursor
from pymongo.asynchronous.cursor import AsyncCursor
from pymongo.synchronous.command_cursor import CommandCursor
from pymongo.synchronous.cursor import Cursor

from client_query_cache._core.cursor_capture import CursorCapture
from client_query_cache._types import NonNegativeInt, PositiveInt
from client_query_cache.asynchronous import CachedCollection as AsyncCachedCollection
from client_query_cache.synchronous import CachedCollection

if TYPE_CHECKING:
    from bson.codec_options import CodecOptions


def live_capture_ids() -> set[NonNegativeInt]:
    # Inspect lifetimes without retaining collectors in the test itself.
    gc.collect()
    # Exact types avoid dereferencing expired weak proxies in the GC inventory.
    return {id(value) for value in gc.get_objects() if type(value) is CursorCapture}


type ReadCursor[DocumentType: Mapping[str, Any]] = (
    Cursor[DocumentType]
    | CommandCursor[DocumentType]
    | AsyncCursor[DocumentType]
    | AsyncCommandCursor[DocumentType]
)


async def resolve_cursor[DocumentType: Mapping[str, Any]](
    cursor: ReadCursor[DocumentType] | Awaitable[AsyncCommandCursor[DocumentType]],
) -> ReadCursor[DocumentType]:
    return await cursor if isinstance(cursor, Awaitable) else cursor


async def materialize[DocumentType: Mapping[str, Any]](
    cursor: ReadCursor[DocumentType] | Awaitable[AsyncCommandCursor[DocumentType]],
    length: PositiveInt | None = None,
) -> list[DocumentType]:
    selected = await resolve_cursor(cursor)
    documents = selected.to_list(length)
    return await documents if isinstance(documents, Awaitable) else documents


async def advance[DocumentType: Mapping[str, Any]](
    cursor: ReadCursor[DocumentType],
) -> DocumentType:
    document = cursor.next()
    return await document if isinstance(document, Awaitable) else document


async def close_cursor[DocumentType: Mapping[str, Any]](
    cursor: ReadCursor[DocumentType],
) -> None:
    cleanup = cursor.close()
    if isinstance(cleanup, Awaitable):
        await cleanup


def with_codec_options[DocumentType: Mapping[str, Any]](
    view: CachedCollection[DocumentType] | AsyncCachedCollection[DocumentType],
    options: CodecOptions[DocumentType],
) -> CachedCollection[DocumentType] | AsyncCachedCollection[DocumentType]:
    if isinstance(view, CachedCollection):
        return CachedCollection(
            view.database, view.raw.with_options(codec_options=options)
        )
    return AsyncCachedCollection(
        view.database, view.raw.with_options(codec_options=options)
    )
