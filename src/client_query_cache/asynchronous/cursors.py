# Protected PyMongo seams are confined to this integration module.
# See docs/development/architecture.md for their supported-version checks.
# ruff: noqa: PLC2701, SLF001
from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from functools import partial
from inspect import signature
from typing import TYPE_CHECKING, Any, Self, cast, override

from pymongo.asynchronous.aggregation import _CollectionAggregationCommand
from pymongo.asynchronous.command_cursor import AsyncCommandCursor
from pymongo.asynchronous.cursor import AsyncCursor

from client_query_cache._core.codec import codec_fingerprint
from client_query_cache._core.cursor_capture import CursorCapture
from client_query_cache._core.order_sensitive_keys import (
    order_sensitive_discriminator_key,
)
from client_query_cache._core.read_classification import query_bypass_reason

if TYPE_CHECKING:
    from pymongo.asynchronous.client_session import AsyncClientSession
    from pymongo.message import _GetMore, _Query

    from client_query_cache.asynchronous.collection import CachedCollection

_FIND_SIGNATURE = signature(AsyncCursor)
_SUPPORTED_FIND_OPTIONS = frozenset(
    {"filter", "projection", "skip", "limit", "sort", "collation", "session"}
)


class CachedCursor[DocumentType: Mapping[str, Any]](AsyncCursor[DocumentType]):
    def __init__(
        self, view: CachedCollection[DocumentType], *args: object, **kwargs: object
    ) -> None:
        self._view = view
        self._capture: CursorCapture | None = None
        self._prepared = False
        self._receiving = False
        self._unsupported = False
        super().__init__(
            view.raw, *cast("tuple[Any, ...]", args), **cast("dict[str, Any]", kwargs)
        )
        supplied = _FIND_SIGNATURE.bind(view.raw, *args, **kwargs).arguments
        self._unsupported = bool(
            supplied.keys() - _SUPPORTED_FIND_OPTIONS - {"collection"}
        )

    async def _prepare(self) -> None:
        self._prepared = True
        unsupported = (
            self._unsupported
            or self._query_flags
            or self._explain
            or any(
                option is not None
                for option in (
                    self._hint,
                    self._comment,
                    self._max_time_ms,
                    self._max_await_time_ms,
                    self._max_scan,
                    self._max,
                    self._min,
                    self._return_key,
                    self._show_record_id,
                    self._snapshot,
                    self._allow_disk_use,
                    self._let,
                )
            )
        )
        discriminator = order_sensitive_discriminator_key(
            (
                "find",
                self._spec,
                self._projection,
                self._ordering,
                self._skip,
                self._limit,
                self._collation,
                codec_fingerprint(self._codec_options),
            )
        )
        reason = (
            self._view._request_bypass_reason(
                session=self._session,
                kwargs={"cursor_options": True} if unsupported else {},
            )
            or query_bypass_reason(self._spec, self._projection, discriminator)
            or await self._view._cache_ineligibility_reason()
        )
        if reason is not None:
            self._view._record_bypass(reason)
            return
        cache = self._view.database.manager.cache_core
        namespace = self._view._namespace()
        lookup = cache.lookup_namespace(
            namespace, discriminator, codec_options=self._codec_options
        )
        if lookup.hit:
            documents = cast("list[DocumentType]", lookup.value)
            self._data = deque(documents)
            self._retrieved = len(documents)
            self._id = 0
            self._killed = True
            return
        if not cache.is_database_available(namespace.database):
            return
        self._capture = CursorCapture(
            cache,
            cache.capture_namespace_generation(namespace),
            discriminator,
            self._codec_options,
        )
        forced = self._view._forced_collection_handle()
        self._read_concern = forced.read_concern
        self._read_preference = forced.read_preference

    @override
    async def _refresh(self) -> int:
        try:
            if not self._prepared and not self._killed:
                await self._prepare()
            return await super()._refresh()
        except BaseException:
            await self.close()
            raise

    @override
    async def _send_message(self, operation: _Query | _GetMore) -> None:
        self._receiving = True
        try:
            await super()._send_message(operation)
        finally:
            self._receiving = False

    def _finish_capture(self) -> None:
        if self._capture is not None and not self.alive:
            self._capture.finish()
            self._capture = None

    @override
    async def next(self) -> DocumentType:
        try:
            document = await super().next()
        except StopAsyncIteration:
            self._finish_capture()
            raise
        if self._capture is not None:
            self._capture.append(document)
        self._finish_capture()
        return document

    @override
    async def _next_batch(
        self, documents: list[DocumentType], total: int | None = None
    ) -> bool:
        start = len(documents)
        available = await super()._next_batch(documents, total)
        if self._capture is not None:
            for index in range(start, len(documents)):
                self._capture.append(documents[index])
        self._finish_capture()
        return available

    @override
    async def close(self) -> None:
        await super().close()
        if not self._receiving:
            if self._capture is not None:
                self._capture.abandon()
                self._capture = None
            self._data.clear()

    @override
    async def rewind(self) -> Self:
        await super().rewind()
        self._prepared = False
        self._read_concern = self.collection.read_concern
        self._read_preference = None
        return self

    @override
    def _clone_base(
        self, session: AsyncClientSession | None
    ) -> CachedCursor[DocumentType]:
        clone = CachedCursor(self._view, session=session)
        clone._unsupported = self._unsupported
        return clone

    @override
    def batch_size(self, batch_size: int) -> Self:
        super().batch_size(batch_size)
        self._unsupported = True
        return self

    @override
    async def add_option(self, mask: int) -> Self:
        await super().add_option(mask)
        self._unsupported = True
        return self

    @override
    def remove_option(self, mask: int) -> Self:
        super().remove_option(mask)
        self._unsupported = True
        return self


class CachedCommandCursor[DocumentType: Mapping[str, Any]](
    AsyncCommandCursor[DocumentType]
):
    def __init__(
        self, *args: object, capture: CursorCapture | None = None, **kwargs: object
    ) -> None:
        self._capture = capture
        self._receiving = False
        super().__init__(
            *cast("tuple[Any, ...]", args), **cast("dict[str, Any]", kwargs)
        )

    def _finish_capture(self) -> None:
        if self._capture is not None and not self.alive:
            self._capture.finish()
            self._capture = None

    @override
    async def _send_message(self, operation: _GetMore) -> None:
        self._receiving = True
        try:
            await super()._send_message(operation)
        finally:
            self._receiving = False

    @override
    async def _refresh(self) -> int:
        try:
            return await super()._refresh()
        except BaseException:
            await self.close()
            raise

    @override
    async def _try_next(self, get_more_allowed: bool) -> DocumentType | None:
        document = await super()._try_next(get_more_allowed)
        if document is not None and self._capture is not None:
            self._capture.append(document)
        self._finish_capture()
        return document

    @override
    async def next(self) -> DocumentType:
        try:
            return await super().next()
        finally:
            self._finish_capture()

    @override
    async def _next_batch(
        self, documents: list[DocumentType], total: int | None = None
    ) -> bool:
        start = len(documents)
        available = await super()._next_batch(documents, total)
        if self._capture is not None:
            for index in range(start, len(documents)):
                self._capture.append(documents[index])
        self._finish_capture()
        return available

    @override
    async def to_list(self, length: int | None = None) -> list[DocumentType]:
        documents = await super().to_list(length)
        self._finish_capture()
        return documents

    @override
    async def close(self) -> None:
        await super().close()
        if not self._receiving:
            if self._capture is not None:
                self._capture.abandon()
                self._capture = None
            self._data.clear()


async def aggregate_miss[DocumentType: Mapping[str, Any]](
    view: CachedCollection[DocumentType],
    pipeline: Sequence[Mapping[str, Any]],
    capture: CursorCapture,
    kwargs: Mapping[str, object],
) -> AsyncCommandCursor[DocumentType]:
    # PyMongo annotates a class but only invokes it as a cursor factory.
    cursor_factory = cast(
        "type[AsyncCommandCursor[DocumentType]]",
        partial(CachedCommandCursor, capture=capture),
    )
    collection = view._forced_collection_handle()
    async with collection.database.client._tmp_session(None) as session:
        return await collection._aggregate(
            _CollectionAggregationCommand,
            pipeline,
            cursor_factory,
            session=session,
            **cast("dict[str, Any]", kwargs),
        )


def prepare_aggregate[DocumentType: Mapping[str, Any]](
    view: CachedCollection[DocumentType],
    pipeline: Sequence[Mapping[str, Any]],
    kwargs: Mapping[str, object],
) -> Mapping[str, Any] | None:
    command = _CollectionAggregationCommand(
        view.raw, AsyncCommandCursor, pipeline, dict(kwargs)
    )
    return command._collation
