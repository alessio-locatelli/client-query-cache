from __future__ import annotations

import time
from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from datetime import datetime
from typing import Any, Literal, override

from bson.codec_options import CodecOptions
from bson.raw_bson import RawBSONDocument
from bson.typings import _DocumentType, _DocumentTypeArg
from pymongo import ReturnDocument, WriteConcern
from pymongo.operations import _IndexKeyHint, _IndexList
from pymongo.read_concern import ReadConcern
from pymongo.read_preferences import _ServerMode
from pymongo.results import (
    BulkWriteResult,
    DeleteResult,
    InsertManyResult,
    InsertOneResult,
    UpdateResult,
)
from pymongo.synchronous.client_session import ClientSession
from pymongo.synchronous.collection import Collection, _WriteOp
from pymongo.synchronous.database import Database
from pymongo.typings import _CollationIn, _Pipeline

from mongo_client_cache._misc import dt_now
from mongo_client_cache._types import BsonDict
from mongo_client_cache.cache import (
    CannotEditImmutableCollectionError,
    CommandCount,
    CommandDistinct,
    command_count_empty_filter,
)
from mongo_client_cache.cache.collection import CollCache
from mongo_client_cache.cache.exceptions import WaitingForChangeStreamError
from mongo_client_cache.logger import logger, logger_debug
from mongo_client_cache.synchronous.cursor import CachedCursor


class CachedCollection(Collection):
    def __init__(  # noqa: PLR0913
        self,
        database: Database[_DocumentType],
        name: str,
        *,
        watch_change_stream: bool,
        create: bool | None = False,
        codec_options: CodecOptions[_DocumentTypeArg] | None = None,
        read_preference: _ServerMode | None = None,
        write_concern: WriteConcern | None = None,
        read_concern: ReadConcern | None = None,
        session: ClientSession | None = None,
    ) -> None:
        super().__init__(
            database,
            name,
            create,
            codec_options,
            read_preference,
            write_concern,
            read_concern,
            session,
        )
        self.__cache = CollCache(self, watch_change_stream=watch_change_stream)
        if watch_change_stream:
            assert self._cache.connected_to_stream.wait(
                self._max_change_stream_await_time_s
            )
        self.__sleep_duration_s = 0.001
        self.__waiting_retry_count = int(
            self._max_change_stream_await_time_s / self.__sleep_duration_s
        )

    def _wait_for_change_stream(
        self, after_dt: datetime, operation_type: Literal["insert", "delete"]
    ) -> None:
        if self._cache.stop_watching or self._cache.watch_stopped:
            logger.debug("Skipped waiting for the change streame because the client is closing.")
            return
        logger_debug(
            f"Waiting for change stream uppdate. "
            + f"{operation_type=}, {after_dt=}"
        )
        for _ in range(self.__waiting_retry_count):
            if self._cache.pending_change_stream[operation_type][after_dt] == 0:
                logger_debug(
                    f"Finished waiting for change stream after {_ * self.__sleep_duration_s} seconds."
                    + f"{operation_type=}, {after_dt=}"
                )
                break
            time.sleep(self.__sleep_duration_s)
            continue
        else:
            raise WaitingForChangeStreamError(
                self._max_change_stream_await_time_s,
                self._cache.pending_change_stream,
            )

    @property
    def _max_change_stream_await_time_s(self) -> float:
        return 10

    @property
    def _cache(self) -> CollCache:
        return self.__cache

    @override
    def bulk_write(
        self,
        requests: Sequence[_WriteOp[_DocumentType]],
        ordered: bool = True,
        bypass_document_validation: bool = False,
        session: ClientSession | None = None,
        comment: Any | None = None,
        let: Mapping | None = None,
    ) -> BulkWriteResult:
        return super().bulk_write(
            requests, ordered, bypass_document_validation, session, comment, let
        )

    @override
    def insert_one(
        self,
        document: _DocumentType | RawBSONDocument,
        bypass_document_validation: bool = False,
        session: ClientSession | None = None,
        comment: Any | None = None,
    ) -> InsertOneResult:
        dt = dt_now()
        insert_one_result = super().insert_one(
            document, bypass_document_validation, session, comment
        )
        self._cache.pending_change_stream["insert"][dt] = 1
        self._wait_for_change_stream(dt, "insert")
        return insert_one_result

    @override
    def insert_many(
        self,
        documents: Iterable[_DocumentType | RawBSONDocument],
        ordered: bool = True,
        bypass_document_validation: bool = False,
        session: ClientSession | None = None,
        comment: Any | None = None,
    ) -> InsertManyResult:
        dt = dt_now()
        insert_many_result = super().insert_many(
            documents, ordered, bypass_document_validation, session, comment
        )
        self._cache.pending_change_stream["insert"][dt] = len(
            insert_many_result.inserted_ids
        )
        self._wait_for_change_stream(dt, "insert")
        return insert_many_result

    @override
    def replace_one(
        self,
        filter: Mapping[str, Any],
        replacement: Mapping[str, Any],
        upsert: bool = False,
        bypass_document_validation: bool = False,
        collation: _CollationIn | None = None,
        hint: _IndexKeyHint | None = None,
        session: ClientSession | None = None,
        let: Mapping[str, Any] | None = None,
        comment: Any | None = None,
    ) -> UpdateResult:
        if __debug__ and not self._cache.watch_change_stream:
            raise CannotEditImmutableCollectionError(self.name)

        return super().replace_one(
            filter,
            replacement,
            upsert,
            bypass_document_validation,
            collation,
            hint,
            session,
            let,
            comment,
        )

    @override
    def update_one(
        self,
        filter: Mapping[str, Any],
        update: Mapping[str, Any] | _Pipeline,
        upsert: bool = False,
        bypass_document_validation: bool = False,
        collation: _CollationIn | None = None,
        array_filters: Sequence[Mapping[str, Any]] | None = None,
        hint: _IndexKeyHint | None = None,
        session: ClientSession | None = None,
        let: Mapping[str, Any] | None = None,
        comment: Any | None = None,
    ) -> UpdateResult:
        if __debug__ and not self._cache.watch_change_stream:
            raise CannotEditImmutableCollectionError(self.name)

        return super().update_one(
            filter,
            update,
            upsert,
            bypass_document_validation,
            collation,
            array_filters,
            hint,
            session,
            let,
            comment,
        )

    @override
    def update_many(
        self,
        filter: Mapping[str, Any],
        update: Mapping[str, Any] | _Pipeline,
        upsert: bool = False,
        array_filters: Sequence[Mapping[str, Any]] | None = None,
        bypass_document_validation: bool | None = None,
        collation: _CollationIn | None = None,
        hint: _IndexKeyHint | None = None,
        session: ClientSession | None = None,
        let: Mapping[str, Any] | None = None,
        comment: Any | None = None,
    ) -> UpdateResult:
        if __debug__ and not self._cache.watch_change_stream:
            raise CannotEditImmutableCollectionError(self.name)

        return super().update_many(
            filter,
            update,
            upsert,
            array_filters,
            bypass_document_validation,
            collation,
            hint,
            session,
            let,
            comment,
        )

    @override
    def delete_one(
        self,
        filter: Mapping[str, Any],
        collation: _CollationIn | None = None,
        hint: _IndexKeyHint | None = None,
        session: ClientSession | None = None,
        let: Mapping[str, Any] | None = None,
        comment: Any | None = None,
    ) -> DeleteResult:
        logger.debug(f"delete_one, {filter=}")
        dt = dt_now()
        delete_one_result = super().delete_one(
            filter, collation, hint, session, let, comment
        )
        if (deleted_count := delete_one_result.deleted_count) == 0:
            return delete_one_result
        self._cache.pending_change_stream["delete"][dt] = deleted_count
        self._wait_for_change_stream(dt, "delete")
        return delete_one_result

    @override
    def delete_many(
        self,
        filter: Mapping[str, Any],
        collation: _CollationIn | None = None,
        hint: _IndexKeyHint | None = None,
        session: ClientSession | None = None,
        let: Mapping[str, Any] | None = None,
        comment: Any | None = None,
    ) -> DeleteResult:
        logger.debug(f"delete, {filter=}")
        dt = dt_now()
        delete_many_result = super().delete_many(
            filter, collation, hint, session, let, comment
        )
        if (deleted_count := delete_many_result.deleted_count) == 0:
            return delete_many_result
        self._cache.pending_change_stream["delete"][dt] = deleted_count
        self._wait_for_change_stream(dt, "delete")
        return delete_many_result

    @override
    def find(self, *args: Any, **kwargs: Any) -> CachedCursor:
        return CachedCursor(self, *args, **kwargs)

    @override
    def find_one(
        self, filter: Any | None = None, *args: Any, **kwargs: Any
    ) -> BsonDict | None:
        if filter is not None and not isinstance(filter, Mapping):
            filter = {"_id": filter}
        cursor = self.find(filter, *args, **kwargs)
        for result in cursor.limit(-1):
            return result
        return None

    @override
    def find_one_and_delete(
        self,
        filter: Mapping[str, Any],
        projection: Mapping[str, Any] | Iterable[str] | None = None,
        sort: _IndexList | None = None,
        hint: _IndexKeyHint | None = None,
        session: ClientSession | None = None,
        let: Mapping[str, Any] | None = None,
        comment: Any | None = None,
        **kwargs: Any,
    ) -> Mapping[str, Any]:
        if __debug__ and not self._cache.watch_change_stream:
            raise CannotEditImmutableCollectionError(self.name)

        return super().find_one_and_delete(
            filter, projection, sort, hint, session, let, comment, **kwargs
        )

    @override
    def find_one_and_replace(
        self,
        filter: Mapping[str, Any],
        replacement: Mapping[str, Any],
        projection: Mapping[str, Any] | Iterable[str] | None = None,
        sort: _IndexList | None = None,
        upsert: bool = False,
        return_document: bool = ReturnDocument.BEFORE,
        hint: _IndexKeyHint | None = None,
        session: ClientSession | None = None,
        let: Mapping[str, Any] | None = None,
        comment: Any | None = None,
        **kwargs: Any,
    ) -> Mapping[str, Any]:
        if __debug__ and not self._cache.watch_change_stream:
            raise CannotEditImmutableCollectionError(self.name)

        return super().find_one_and_replace(
            filter,
            replacement,
            projection,
            sort,
            upsert,
            return_document,
            hint,
            session,
            let,
            comment,
            **kwargs,
        )

    @override
    def find_one_and_update(
        self,
        filter: Mapping[str, Any],
        update: Mapping[str, Any] | _Pipeline,
        projection: Mapping[str, Any] | Iterable[str] | None = None,
        sort: _IndexList | None = None,
        upsert: bool = False,
        return_document: bool = ReturnDocument.BEFORE,
        array_filters: Sequence[Mapping[str, Any]] | None = None,
        hint: _IndexKeyHint | None = None,
        session: ClientSession | None = None,
        let: Mapping[str, Any] | None = None,
        comment: Any | None = None,
        **kwargs: Any,
    ) -> Mapping[str, Any]:
        if __debug__ and not self._cache.watch_change_stream:
            raise CannotEditImmutableCollectionError(self.name)

        return super().find_one_and_update(
            filter,
            update,
            projection,
            sort,
            upsert,
            return_document,
            array_filters,
            hint,
            session,
            let,
            comment,
            **kwargs,
        )

    @override
    def count_documents(
        self,
        filter: Mapping[str, Any],
        session: ClientSession | None = None,
        comment: Any | None = None,
        **kwargs: Any,
    ) -> int:
        logger_debug(f"'count', {filter=}.")
        query = str(
            CommandCount(
                filter,
                skip=kwargs.get("skip", 0),
                limit=kwargs.get("limit", 0),
            )
        )
        try:
            return self._cache.document_count[query]
        except KeyError:
            document_count = super().count_documents(filter, session, comment, **kwargs)
            self._cache.document_count[query] = document_count
            if query == command_count_empty_filter:
                self._cache.estimated_document_count = document_count
            return document_count

    @override
    def estimated_document_count(
        self, comment: Any | None = None, **kwargs: Any
    ) -> int:
        logger_debug(f"'estimated_document_count', {filter=}.")
        if self._cache.estimated_document_count is not None:
            return self._cache.estimated_document_count
        document_count = super().estimated_document_count(comment, **kwargs)
        self._cache.estimated_document_count = document_count
        return document_count

    @override
    def distinct(
        self,
        key: str,
        filter: Mapping[str, Any] | None = None,
        session: ClientSession | None = None,
        comment: Any | None = None,
        **kwargs: Any,
    ) -> list:
        query = str(CommandDistinct(key=key, filter=filter))
        try:
            return self._cache.distinct[query]
        except KeyError:
            distinct_values = super().distinct(key, filter, session, comment, **kwargs)
            self._cache.distinct[query] = distinct_values
            return distinct_values

    @override
    def drop(
        self,
        session: ClientSession | None = None,
        comment: Any | None = None,
        encrypted_fields: Mapping[str, Any] | None = None,
    ) -> None:
        if __debug__ and not self._cache.watch_change_stream:
            raise CannotEditImmutableCollectionError(self.name)

        return super().drop(session, comment, encrypted_fields)

    @override
    def rename(
        self,
        new_name: str,
        session: ClientSession | None = None,
        comment: Any | None = None,
        **kwargs: Any,
    ) -> MutableMapping[str, Any]:
        if __debug__ and self._cache.watch_change_stream:
            raise CannotEditImmutableCollectionError(self.name)

        return super().rename(new_name, session, comment, **kwargs)
