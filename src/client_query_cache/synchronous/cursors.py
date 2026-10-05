# Protected PyMongo seams are confined to this integration module.
# See docs/development/architecture.md for their supported-version checks.
# ruff: noqa: PLC2701, SLF001
from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from functools import partial
from inspect import signature
from typing import TYPE_CHECKING, Any, Self, cast, override

from pymongo.synchronous.aggregation import _CollectionAggregationCommand
from pymongo.synchronous.command_cursor import CommandCursor
from pymongo.synchronous.cursor import Cursor

from client_query_cache._core.codec import codec_fingerprint
from client_query_cache._core.cursor_capture import CursorCapture
from client_query_cache._core.find_reads import find_read_shape
from client_query_cache._core.read_classification import query_bypass_reason

if TYPE_CHECKING:
    from pymongo.message import _GetMore, _Query
    from pymongo.synchronous.client_session import ClientSession

    from client_query_cache.synchronous.collection import CachedCollection

_FIND_SIGNATURE = signature(Cursor)
_SUPPORTED_FIND_OPTIONS = frozenset(
    {"filter", "projection", "skip", "limit", "sort", "collation", "session"}
)


class CachedCursor[DocumentType: Mapping[str, Any]](Cursor[DocumentType]):
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

    def _prepare(self) -> None:
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
        shape = find_read_shape(
            self._spec,
            self._projection,
            self._ordering,
            self._skip,
            self._limit,
            collation=self._collation,
            codec=codec_fingerprint(self._codec_options),
        )
        discriminator = shape.discriminator
        reason = (
            self._view._request_bypass_reason(
                session=self._session,
                kwargs={"cursor_options": True} if unsupported else {},
            )
            or query_bypass_reason(self._spec, self._projection, discriminator)
            or self._view._cache_ineligibility_reason()
        )
        if reason is not None:
            self._view._record_bypass(reason)
            return
        cache = self._view.database.manager.cache_core
        namespace = self._view._namespace()
        lookup = cache.lookup_find(namespace, shape, codec_options=self._codec_options)
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
            find_source=shape.source,
        )
        forced = self._view._forced_collection_handle()
        self._read_concern = forced.read_concern
        self._read_preference = forced.read_preference

    @override
    def _refresh(self) -> int:
        try:
            if not self._prepared and not self._killed:
                self._prepare()
            return super()._refresh()
        except BaseException:
            self.close()
            raise

    @override
    def _send_message(self, operation: _Query | _GetMore) -> None:
        self._receiving = True
        try:
            super()._send_message(operation)
        finally:
            self._receiving = False

    def _finish_capture(self) -> None:
        if self._capture is not None and not self.alive:
            self._capture.finish()
            self._capture = None

    @override
    def next(self) -> DocumentType:
        try:
            document = super().next()
        except StopIteration:
            self._finish_capture()
            raise
        if self._capture is not None:
            self._capture.append(document)
        self._finish_capture()
        return document

    @override
    def _next_batch(
        self, documents: list[DocumentType], total: int | None = None
    ) -> bool:
        start = len(documents)
        available = super()._next_batch(documents, total)
        if self._capture is not None:
            for index in range(start, len(documents)):
                self._capture.append(documents[index])
        self._finish_capture()
        return available

    @override
    def close(self) -> None:
        super().close()
        if not self._receiving:
            if self._capture is not None:
                self._capture.abandon()
                self._capture = None
            self._data.clear()

    @override
    def rewind(self) -> Self:
        super().rewind()
        self._prepared = False
        self._read_concern = self.collection.read_concern
        self._read_preference = None
        return self

    @override
    def _clone_base(self, session: ClientSession | None) -> CachedCursor[DocumentType]:
        clone = CachedCursor(self._view, session=session)
        clone._unsupported = self._unsupported
        return clone

    @override
    def batch_size(self, batch_size: int) -> Self:
        super().batch_size(batch_size)
        self._unsupported = True
        return self

    @override
    def add_option(self, mask: int) -> Self:
        super().add_option(mask)
        self._unsupported = True
        return self

    @override
    def remove_option(self, mask: int) -> Self:
        super().remove_option(mask)
        self._unsupported = True
        return self


class CachedCommandCursor[DocumentType: Mapping[str, Any]](CommandCursor[DocumentType]):
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
    def _send_message(self, operation: _GetMore) -> None:
        self._receiving = True
        try:
            super()._send_message(operation)
        finally:
            self._receiving = False

    @override
    def _refresh(self) -> int:
        try:
            return super()._refresh()
        except BaseException:
            self.close()
            raise

    @override
    def _try_next(self, get_more_allowed: bool) -> DocumentType | None:
        document = super()._try_next(get_more_allowed)
        if document is not None and self._capture is not None:
            self._capture.append(document)
        self._finish_capture()
        return document

    @override
    def next(self) -> DocumentType:
        try:
            return super().next()
        finally:
            self._finish_capture()

    @override
    def _next_batch(
        self, documents: list[DocumentType], total: int | None = None
    ) -> bool:
        start = len(documents)
        available = super()._next_batch(documents, total)
        if self._capture is not None:
            for index in range(start, len(documents)):
                self._capture.append(documents[index])
        self._finish_capture()
        return available

    @override
    def to_list(self, length: int | None = None) -> list[DocumentType]:
        # Finalize only after native to_list validation and consumption succeed.
        documents = super().to_list(length)
        self._finish_capture()
        return documents

    @override
    def close(self) -> None:
        super().close()
        if not self._receiving:
            if self._capture is not None:
                self._capture.abandon()
                self._capture = None
            self._data.clear()


def aggregate_miss[DocumentType: Mapping[str, Any]](
    view: CachedCollection[DocumentType],
    pipeline: Sequence[Mapping[str, Any]],
    capture: CursorCapture,
    kwargs: Mapping[str, object],
) -> CommandCursor[DocumentType]:
    # PyMongo annotates a class but only invokes it as a cursor factory.
    cursor_factory = cast(
        "type[CommandCursor[DocumentType]]",
        partial(CachedCommandCursor, capture=capture),
    )
    collection = view._forced_collection_handle()
    with collection.database.client._tmp_session(None) as session:
        return collection._aggregate(
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
        view.raw, CommandCursor, pipeline, dict(kwargs)
    )
    return command._collation
