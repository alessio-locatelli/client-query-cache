from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from typing import Any, cast, override

from bson.raw_bson import RawBSONDocument
from bson.typings import _DocumentType
from pymongo import ReturnDocument
from pymongo.synchronous.client_session import ClientSession
from pymongo.synchronous.collection import Collection, _WriteOp
from pymongo.operations import _IndexKeyHint, _IndexList
from pymongo.results import (
    BulkWriteResult,
    DeleteResult,
    InsertManyResult,
    InsertOneResult,
    UpdateResult,
)
from pymongo.typings import _CollationIn, _Pipeline

from mongo_client_cache.core.exceptions import (
    CannotEditImmutableCollectionError
)
from mongo_client_cache.core.local_database import DatabaseCache
from mongo_client_cache.core.misc import CommandCount, CommandDistinct
from mongo_client_cache.synchronous.cursor import CachedCursor
from mongo_client_cache.types import BsonDict


class CachedCollection(Collection):
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
        if __debug__:
            db = self._Collection__database
            cache = cast(
                DatabaseCache, db._Database__client._client_side_databases[db.name]
            )
            if self.name in cache.static_collections_names:
                raise CannotEditImmutableCollectionError(self.name)

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
        if __debug__:
            db = self._Collection__database
            cache = cast(
                DatabaseCache, db._Database__client._client_side_databases[db.name]
            )
            if self.name in cache.static_collections_names:
                raise CannotEditImmutableCollectionError(self.name)

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
        if __debug__:
            db = self._Collection__database
            cache = cast(
                DatabaseCache, db._Database__client._client_side_databases[db.name]
            )
            if self.name in cache.static_collections_names:
                raise CannotEditImmutableCollectionError(self.name)

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
        if __debug__:
            db = self._Collection__database
            cache = cast(
                DatabaseCache, db._Database__client._client_side_databases[db.name]
            )
            if self.name in cache.static_collections_names:
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
        if __debug__:
            db = self._Collection__database
            cache = cast(
                DatabaseCache, db._Database__client._client_side_databases[db.name]
            )
            if self.name in cache.static_collections_names:
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
        if __debug__:
            db = self._Collection__database
            cache = cast(
                DatabaseCache, db._Database__client._client_side_databases[db.name]
            )
            if self.name in cache.static_collections_names:
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
        if __debug__:
            db = self._Collection__database
            cache = cast(
                DatabaseCache, db._Database__client._client_side_databases[db.name]
            )
            if self.name in cache.static_collections_names:
                raise CannotEditImmutableCollectionError(self.name)

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
        if __debug__:
            db = self._Collection__database
            cache = cast(
                DatabaseCache, db._Database__client._client_side_databases[db.name]
            )
            if self.name in cache.static_collections_names:
                raise CannotEditImmutableCollectionError(self.name)

        return super().delete_many(filter, collation, hint, session, let, comment)

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
        if __debug__:
            db = self._Collection__database
            cache = cast(
                DatabaseCache, db._Database__client._client_side_databases[db.name]
            )
            if self.name in cache.static_collections_names:
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
        if __debug__:
            db = self._Collection__database
            cache = cast(
                DatabaseCache, db._Database__client._client_side_databases[db.name]
            )
            if self.name in cache.static_collections_names:
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
        if __debug__:
            db = self._Collection__database
            cache = cast(
                DatabaseCache, db._Database__client._client_side_databases[db.name]
            )
            if self.name in cache.static_collections_names:
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
        db = self._Collection__database
        cache = db._Database__client._client_side_databases[db.name]
        query = str(CommandCount(
            filter,
            skip=kwargs.get("skip", 0),
            limit=kwargs.get("limit", 0),
        ))
        try:
            return cache.document_count_per_collection[self.name][query]
        except KeyError:
            document_count = super().count_documents(filter, session, comment, **kwargs)
            cache.document_count_per_collection[self.name][query] = document_count
            return document_count

    @override
    def estimated_document_count(
        self, comment: Any | None = None, **kwargs: Any
    ) -> int:
        db = self._Collection__database
        cache = db._Database__client._client_side_databases[db.name]
        try:
            return cache.estimated_document_count_per_collection[self.name]
        except KeyError:
            document_count = super().estimated_document_count(comment, **kwargs)
            cache.estimated_document_count_per_collection[self.name] = document_count
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
        db = self._Collection__database
        cache = db._Database__client._client_side_databases[db.name]
        query = str(CommandDistinct(filter, key=key))
        try:
            return cache.distinct_per_collection[self.name][query]
        except KeyError:
            distinct_values = super().distinct(key, filter, session, comment, **kwargs)
            cache.distinct_per_collection[self.name][query] = distinct_values
            return distinct_values

    @override
    def drop(
        self,
        session: ClientSession | None = None,
        comment: Any | None = None,
        encrypted_fields: Mapping[str, Any] | None = None,
    ) -> None:
        if __debug__:
            db = self._Collection__database
            cache = cast(
                DatabaseCache, db._Database__client._client_side_databases[db.name]
            )
            if self.name in cache.static_collections_names:
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
        if __debug__:
            db = self._Collection__database
            cache = cast(
                DatabaseCache, db._Database__client._client_side_databases[db.name]
            )
            if self.name in cache.static_collections_names:
                raise CannotEditImmutableCollectionError(self.name)

        return super().rename(new_name, session, comment, **kwargs)
