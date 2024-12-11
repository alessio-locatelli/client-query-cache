from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from typing import Any, override

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

from mongo_client_cache._types import BsonDict
from mongo_client_cache.cache import (
    CannotEditImmutableCollectionError,
    CommandCount,
    CommandDistinct,
    command_count_empty_filter,
)
from mongo_client_cache.cache.collection import CollCache
from mongo_client_cache.cache.exceptions import WaitingForChangeStreamError
from mongo_client_cache.logger import logger
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

    @property
    def _max_change_stream_await_time_s(self) -> float:
        return 20

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
        self._cache.change_stream_refreshed["insert"].clear()
        return super().insert_one(
            document, bypass_document_validation, session, comment
        )

    @override
    def insert_many(
        self,
        documents: Iterable[_DocumentType | RawBSONDocument],
        ordered: bool = True,
        bypass_document_validation: bool = False,
        session: ClientSession | None = None,
        comment: Any | None = None,
    ) -> InsertManyResult:
        self._cache.change_stream_refreshed["insert"].clear()
        return super().insert_many(
            documents, ordered, bypass_document_validation, session, comment
        )

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
        self._cache.change_stream_refreshed["delete"].clear()
        # logger.debug(f"delete_one, {filter}, {self._cache.change_stream_refreshed}")        
        return super().delete_one(filter, collation, hint, session, let, comment)

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
        self._cache.change_stream_refreshed["delete"].clear()
        return super().delete_many(filter, collation, hint, session, let, comment)

    @override
    def find(self, *args: Any, **kwargs: Any) -> CachedCursor:
        if (
            self._cache.change_stream_refreshed["insert"].wait(
                self._max_change_stream_await_time_s
            )
            is False
            or self._cache.change_stream_refreshed["delete"].wait(
                self._max_change_stream_await_time_s
            )
            is False
        ):
            raise WaitingForChangeStreamError(self._max_change_stream_await_time_s)

        return CachedCursor(self, *args, **kwargs)

    @override
    def find_one(
        self, filter: Any | None = None, *args: Any, **kwargs: Any
    ) -> BsonDict | None:
        if (
            self._cache.change_stream_refreshed["insert"].wait(
                self._max_change_stream_await_time_s
            )
            is False
            or self._cache.change_stream_refreshed["delete"].wait(
                self._max_change_stream_await_time_s
            )
            is False
        ):
            raise WaitingForChangeStreamError(self._max_change_stream_await_time_s)
        
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
        query = str(
            CommandCount(
                filter,
                skip=kwargs.get("skip", 0),
                limit=kwargs.get("limit", 0),
            )
        )
        logger.debug(f"count_documents, {query}, {self._cache.change_stream_refreshed}")
        if (
            self._cache.change_stream_refreshed["insert"].wait(
                self._max_change_stream_await_time_s
            )
            is False
            or self._cache.change_stream_refreshed["delete"].wait(
                self._max_change_stream_await_time_s
            )
            is False
        ):
            raise WaitingForChangeStreamError(self._max_change_stream_await_time_s)

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
        if (
            self._cache.change_stream_refreshed["insert"].wait(
                self._max_change_stream_await_time_s
            )
            is False
            or self._cache.change_stream_refreshed["delete"].wait(
                self._max_change_stream_await_time_s
            )
            is False
        ):
            raise WaitingForChangeStreamError(self._max_change_stream_await_time_s)

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
        cache = self.database.client._client_side_databases[self.database.name]
        query = str(CommandDistinct(filter, key=key))
        try:
            return cache.distinct_per_collection[self.name][query]
        except KeyError:
            distinct_values = super().distinct(key, filter, session, comment, **kwargs)
            cache.distinct_per_collection[self.name][query] = distinct_values
            return distinct_values  # type: ignore[unreachable]

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
