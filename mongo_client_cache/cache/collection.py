from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from threading import Event, Thread

import pymongo
from bson import ObjectId, Timestamp
from pymongo.synchronous.collection import Collection

from mongo_client_cache._types import BsonDict, BsonValue, ChangeStreamDocument
from mongo_client_cache.cache.change_stream import pipeline
from mongo_client_cache.cache.commands import CommandKwargs, command_count_empty_filter
from mongo_client_cache.cache.exceptions import UnexpectedChangeOperationTypeError
from mongo_client_cache.logger import logger, logger_debug


class CollCache:
    __slots__ = (
        "_collection",
        "_start_at_operation_time",
        "connected_to_stream",
        "distinct",
        "distinct_per_collection",
        "document_count",
        "documents",
        "estimated_document_count",
        "pending_change_stream",
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
            self.pending_change_stream: dict[str, dict[datetime, int]] = {
                "insert": {},
                "delete": {},
            }
            self._start_at_operation_time = datetime.now(UTC)
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
        start_at_operation_time = Timestamp(
            # NOTE: For some reason we need to start watching a few seconds earlier.
            int(self._start_at_operation_time.timestamp()) - 5,
            0,
        )
        logger.debug(
            f'Watching Change Stream for "{self._collection.name}" collection.'
            + f"{start_at_operation_time=}"
        )
        with self._collection.watch(
            pipeline, start_at_operation_time=start_at_operation_time
        ) as stream:
            self.connected_to_stream.set()
            logger_debug(f"Connected to the '{self._collection.name}' change stream.")
            try:
                for change in stream:
                    if self.stop_watching:
                        logger.debug(
                            f"Stopping watching changes on {self._collection.name} collection."  # noqa: E501
                        )
                        self.watch_stopped.set()
                        break
                    self._process_change_stream(change)
            except pymongo.synchronous.pool._PoolClosedError as error:
                logger.debug(repr(error))
                return

    def _insert(self, change: ChangeStreamDocument) -> None:  # ObjectId or str?
        for dt, i in self.pending_change_stream["insert"].items():
            if change["wallTime"] >= dt and i > 0:
                self.pending_change_stream["insert"][dt] -= 1
                break

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
        for dt, i in self.pending_change_stream["delete"].items():
            if change["wallTime"] >= dt and i > 0:
                self.pending_change_stream["delete"][dt] -= 1
                break

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
            + f"{self.pending_change_stream}"
        )

        if operation_type == "insert":
            self._insert(change)
        elif operation_type == "update":
            self._update(change)
        elif operation_type == "replace":
            self._replace(change)
        elif operation_type == "delete":
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
