from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from itertools import count
from threading import Event, Thread

import pymongo
from bson import ObjectId, Timestamp
from pymongo.errors import PyMongoError
from pymongo.synchronous.collection import Collection

from mongo_client_cache._types import BsonDict, BsonValue, ChangeStreamDocument
from mongo_client_cache.cache.change_stream import pipeline
from mongo_client_cache.cache.commands import CommandKwargs, command_count_empty_filter
from mongo_client_cache.cache.exceptions import UnexpectedChangeOperationTypeError
from mongo_client_cache.logger import logger, logger_debug


class _StopWatchingError(Exception): ...


class CollCache:
    _change_stream_max_retries = 3

    __slots__ = (
        "_collection",
        "_resume_token",
        "_start_at_operation_time",
        "change_stream_refreshed",
        "connected_to_stream",
        "distinct",
        "distinct_per_collection",
        "document_count",
        "documents",
        "estimated_document_count",
        "query_to_ids_map",
        "stop_watching",
        "watch_change_stream",
        "watch_stopped",
    )

    def __init__(self, /, collection: Collection, *, watch_change_stream: bool) -> None:
        self._collection = collection

        # Local in-memory storage (MongoDB collection cache).
        self.query_to_ids_map: dict[CommandKwargs, deque[ObjectId | str]] = {}
        self.document_count: dict[CommandKwargs, int] = {}
        self.estimated_document_count: int | None = None
        self.distinct: dict[CommandKwargs, list[BsonValue]] = {}
        self.documents: dict[ObjectId | str, BsonDict] = {}  # NOTE: What is a key?

        # Change stream.
        self.watch_change_stream = watch_change_stream
        if watch_change_stream:
            self._start_at_operation_time = datetime.now(UTC)
            self.change_stream_refreshed = {"insert": Event(), "delete": Event()}
            for e in self.change_stream_refreshed.values():
                e.set()
            self.connected_to_stream = Event()
            self.watch_stopped = Event()
            self.watch_change_stream = watch_change_stream
            self.stop_watching = False
            Thread(target=self.watch, daemon=True).start()

    def watch(self) -> None:
        """
        https://github.com/mongodb/specifications/blob/master/source/change-streams/change-streams.rst
        https://www.mongodb.com/docs/manual/reference/change-events/#change-events
        """
        self._resume_token: dict[str, str] | None = None

        for retry_attempt in count():
            if self.stop_watching:
                logger.debug(
                    f"Stopping watching changes on {self._collection.name} collection."
                )
                self.watch_stopped.set()
                break
            try:
                self._watch()
            except PyMongoError as error:
                # The ChangeStream encountered an unrecoverable error or the
                # resume attempt failed to recreate the cursor.
                if self._resume_token is None:
                    if retry_attempt == self._change_stream_max_retries:
                        raise
                    logger.error(
                        "There is no usable resume token because there was a "
                        + "failure during ChangeStream initialization. "
                        + f"Target: '{self._collection}', {retry_attempt=}, {error!r}."
                    )
                raise
            except _StopWatchingError:
                break

    def _watch(self) -> None:
        if self.stop_watching:
            logger.debug(
                f"Stopping watching changes on {self._collection.name} collection."
            )
            self.watch_stopped.set()
            raise _StopWatchingError

        start_at_operation_time = Timestamp(
            # NOTE: For some reason we need to start watching a few seconds earlier.
            int(self._start_at_operation_time.timestamp()) - 5,
            0,
        )
        logger.debug(
            f'Watching Change Stream for "{self._collection.name}" collection. {start_at_operation_time=}'  # noqa: E501
        )
        with self._collection.watch(
            pipeline,
            resume_after=self._resume_token,
            start_at_operation_time=start_at_operation_time,
        ) as stream:
            self.connected_to_stream.set()
            logger.debug(f"Connected to the '{self._collection.name}' change stream.")
            try:
                for change in stream:
                    if self.stop_watching:
                        logger.debug(  # type: ignore[unreachable]
                            f"Stopping watching changes on {self._collection.name} collection."  # noqa: E501
                        )
                        self.watch_stopped.set()
                        raise _StopWatchingError
                    self._process_change_stream(change)

                    # Use the interrupted ChangeStream's resume token to create
                    # a new ChangeStream. The new stream will continue from the
                    # last seen insert change without missing any events.
                    if self._resume_token is None:
                        logger_debug(
                            f"Assigning a new 'resumeAfter': '{stream.resume_token['_data'][:5]}[...]'"  # type: ignore[index]  # noqa: E501
                        )
                    self._resume_token = stream.resume_token["_data"]  # type: ignore[index]
            except pymongo.synchronous.pool._PoolClosedError as e:
                logger.debug(e)
                raise _StopWatchingError from e

    def _insert(self, change: ChangeStreamDocument) -> None:  # ObjectId or str?
        if self.estimated_document_count is not None:
            self.estimated_document_count += 1
        try:
            self.document_count[command_count_empty_filter] += 1
            logger_debug(f"document_count={self.document_count}")
        except KeyError:
            pass
        # Invalidate all cached queries.
        self.query_to_ids_map.clear()
        self.distinct.clear()

    def _update(self, change: ChangeStreamDocument) -> None:
        raise NotImplementedError

    def _replace(self, change: ChangeStreamDocument) -> None:
        raise NotImplementedError

    def _delete(self, change: ChangeStreamDocument) -> None:
        try:
            del self.documents[change["documentKey"]["_id"]]
        except KeyError:
            pass
        if self.estimated_document_count is not None:
            self.estimated_document_count -= 1
        try:
            self.document_count[command_count_empty_filter] -= 1
        except KeyError:
            pass
        # Invalidate all cached queries.
        self.query_to_ids_map.clear()
        self.distinct.clear()

    def _drop(self, change: ChangeStreamDocument) -> None:
        self.query_to_ids_map.clear()
        self.document_count.clear()
        self.estimated_document_count = None
        self.distinct.clear()

    def _rename(self, change: ChangeStreamDocument) -> None:
        raise NotImplementedError

    def _process_change_stream(self, change: ChangeStreamDocument) -> None:
        operation_type = change["operationType"]
        logger_debug(
            f"operationType={operation_type}, wallTime={change['wallTime']}, "
            + f"documentKey={change['documentKey']['_id']}, "
            + f"{ {k: v.is_set() for k, v in self.change_stream_refreshed.items()} }"
        )

        if operation_type == "insert":
            self.change_stream_refreshed["insert"].set()
            self._insert(change)
        elif operation_type == "update":
            self._update(change)
        elif operation_type == "replace":
            self._replace(change)
        elif operation_type == "delete":
            self.change_stream_refreshed["delete"].set()
            self._delete(change)
        elif operation_type == "drop":
            self._drop(change)
        elif operation_type == "rename":
            self._rename(change)
        else:
            raise UnexpectedChangeOperationTypeError(change["operationType"])

    def clear(self) -> None:
        self.query_to_ids_map.clear()
        self.document_count.clear()
        self.estimated_document_count = None
        self.distinct.clear()
