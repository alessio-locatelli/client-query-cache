from collections.abc import Iterable, Iterator, Mapping, MutableMapping, Sequence
from typing import Any, cast

from bson.raw_bson import RawBSONDocument
from bson.typings import _DocumentType
from pymongo import ReturnDocument
from pymongo.client_session import ClientSession
from pymongo.collection import Collection, _WriteOp
from pymongo.cursor import Cursor
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
    CannotEditImmutableCollectionError,
    NotCachedError,
)
from mongo_client_cache.core.local_database import ClientSideDatabase, MongoCommand

from mongo_client_cache.types import BsonDict


class CachedCollection(Collection):
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
            db = self.__Collection__database
            cache = cast(ClientSideDatabase, db.client.client_side_databases[db.name])
            if self.name in cache.static_collections:
                raise CannotEditImmutableCollectionError(self.name)

        return super().bulk_write(
            requests, ordered, bypass_document_validation, session, comment, let
        )

    def insert_one(
        self,
        document: _DocumentType | RawBSONDocument,
        bypass_document_validation: bool = False,
        session: ClientSession | None = None,
        comment: Any | None = None,
    ) -> InsertOneResult:
        if __debug__:
            db = self.__Collection__database
            cache = cast(ClientSideDatabase, db.client.client_side_databases[db.name])
            if self.name in cache.static_collections:
                raise CannotEditImmutableCollectionError(self.name)

        return super().insert_one(
            document, bypass_document_validation, session, comment
        )

    def insert_many(
        self,
        documents: Iterable[_DocumentType | RawBSONDocument],
        ordered: bool = True,
        bypass_document_validation: bool = False,
        session: ClientSession | None = None,
        comment: Any | None = None,
    ) -> InsertManyResult:
        if __debug__:
            db = self.__Collection__database
            cache = cast(ClientSideDatabase, db.client.client_side_databases[db.name])
            if self.name in cache.static_collections:
                raise CannotEditImmutableCollectionError(self.name)

        return super().insert_many(
            documents, ordered, bypass_document_validation, session, comment
        )

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
            db = self.__Collection__database
            cache = cast(ClientSideDatabase, db.client.client_side_databases[db.name])
            if self.name in cache.static_collections:
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
            db = self.__Collection__database
            cache = cast(ClientSideDatabase, db.client.client_side_databases[db.name])
            if self.name in cache.static_collections:
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
            db = self.__Collection__database
            cache = cast(ClientSideDatabase, db.client.client_side_databases[db.name])
            if self.name in cache.static_collections:
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
            db = self.__Collection__database
            cache = cast(ClientSideDatabase, db.client.client_side_databases[db.name])
            if self.name in cache.static_collections:
                raise CannotEditImmutableCollectionError(self.name)

        return super().delete_one(filter, collation, hint, session, let, comment)

    def delete_many(
        self,
        filter: Mapping[str, Any],
        collation: _CollationIn | None = None,
        hint: _IndexKeyHint | None = None,
        session: ClientSession | None = None,
        let: Mapping[str, Any] | None = None,
        comment: Any | None = None,
    ) -> DeleteResult:
        db = self.__Collection__database
        cache = cast(ClientSideDatabase, db.client.client_side_databases[db.name])
        if self.name in cache.static_collections:
            raise CannotEditImmutableCollectionError(self.name)

        return super().delete_many(filter, collation, hint, session, let, comment)

    def find(self, *args: Any, **kwargs: Any) -> Iterator[BsonDict]:  # type: ignore[override]
        db = self.__Collection__database
        cache = cast(ClientSideDatabase, db.client.client_side_databases[db.name])

        if self.name in cache.excluded_collections:
            return super().find(*args, **kwargs)

        mongo_command = MongoCommand(
            self.name,
            "find",
            filter=args[0] if args else kwargs.pop("filter"),
            projection=kwargs.pop("projection"),
        )
        try:
            cached_documents = cache.get_many(mongo_command=mongo_command)
        except NotCachedError:
            documents = []
            for document in Cursor(self, *args, **kwargs):
                documents.append(document)
                yield document

            cache.set_many(documents=documents, mongo_command=mongo_command)
        else:
            yield from cached_documents

    def find_one(
        self,
        filter: Any | None = None,
        *args: Any,
        projection: list[str] | dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> BsonDict | None:
        db = self.__Collection__database
        cache = cast(ClientSideDatabase, db.client.client_side_databases[db.name])

        if self.name in cache.excluded_collections:
            return super().find_one(filter, *args, **kwargs)

        try:
            return cache.get_one(
                mongo_command=MongoCommand(self.name, "findOne", filter, projection),
            )
        except NotCachedError:
            document = super().find_one(filter, *args, **kwargs)
            cache.set_one(
                document=document,
                mongo_command=MongoCommand(self.name, "findOne", filter, projection),
            )
            return document

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
    ) -> _DocumentType:
        if __debug__:
            db = self.__Collection__database
            cache = cast(ClientSideDatabase, db.client.client_side_databases[db.name])
            if self.name in cache.static_collections:
                raise CannotEditImmutableCollectionError(self.name)

        return super().find_one_and_delete(
            filter, projection, sort, hint, session, let, comment, **kwargs
        )

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
    ) -> _DocumentType:
        if __debug__:
            db = self.__Collection__database
            cache = cast(ClientSideDatabase, db.client.client_side_databases[db.name])
            if self.name in cache.static_collections:
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
    ) -> _DocumentType:
        if __debug__:
            db = self.__Collection__database
            cache = cast(ClientSideDatabase, db.client.client_side_databases[db.name])
            if self.name in cache.static_collections:
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

    def count_documents(
        self,
        filter: Mapping[str, Any],
        session: ClientSession | None = None,
        comment: Any | None = None,
        **kwargs: Any,
    ) -> int:
        return super().count_documents(filter, session, comment, **kwargs)

    def estimated_document_count(
        self, comment: Any | None = None, **kwargs: Any
    ) -> int:
        return super().estimated_document_count(comment, **kwargs)

    def distinct(
        self,
        key: str,
        filter: Mapping[str, Any] | None = None,
        session: ClientSession | None = None,
        comment: Any | None = None,
        **kwargs: Any,
    ) -> list:
        return super().distinct(key, filter, session, comment, **kwargs)

    def drop(
        self,
        session: ClientSession | None = None,
        comment: Any | None = None,
        encrypted_fields: Mapping[str, Any] | None = None,
    ) -> None:
        if __debug__:
            db = self.__Collection__database
            cache = cast(ClientSideDatabase, db.client.client_side_databases[db.name])
            if self.name in cache.static_collections:
                raise CannotEditImmutableCollectionError(self.name)

        return super().drop(session, comment, encrypted_fields)

    def rename(
        self,
        new_name: str,
        session: ClientSession | None = None,
        comment: Any | None = None,
        **kwargs: Any,
    ) -> MutableMapping[str, Any]:
        if __debug__:
            db = self.__Collection__database
            cache = cast(ClientSideDatabase, db.client.client_side_databases[db.name])
            if self.name in cache.static_collections:
                raise CannotEditImmutableCollectionError(self.name)

        return super().rename(new_name, session, comment, **kwargs)
