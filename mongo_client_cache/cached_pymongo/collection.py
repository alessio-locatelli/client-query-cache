from collections.abc import Iterable, Iterator, Mapping, MutableMapping, Sequence
from typing import Any, cast, Optional, Union
from bson.raw_bson import RawBSONDocument
from pymongo import ReturnDocument
from pymongo.client_session import ClientSession

from pymongo.collection import Collection, _WriteOp
from pymongo.cursor import Cursor

from pymongo.operations import _IndexKeyHint, _IndexList
from pymongo.typings import _Pipeline
from bson.typings import _DocumentType
from pymongo.results import (
    BulkWriteResult,
    DeleteResult,
    InsertManyResult,
    InsertOneResult,
    UpdateResult,
)
from pymongo.typings import _CollationIn
from mongo_client_cache.backends.base import MongoCommand
from mongo_client_cache.backends.memory import MemoryBackend
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
        return super().bulk_write(
            requests, ordered, bypass_document_validation, session, comment, let
        )

    def insert_one(
        self,
        document: Union[_DocumentType, RawBSONDocument],
        bypass_document_validation: bool = False,
        session: Optional[ClientSession] = None,
        comment: Optional[Any] = None,
    ) -> InsertOneResult:
        return super().insert_one(
            document, bypass_document_validation, session, comment
        )

    def insert_many(
        self,
        documents: Iterable[Union[_DocumentType, RawBSONDocument]],
        ordered: bool = True,
        bypass_document_validation: bool = False,
        session: Optional[ClientSession] = None,
        comment: Optional[Any] = None,
    ) -> InsertManyResult:
        return super().insert_many(
            documents, ordered, bypass_document_validation, session, comment
        )

    def replace_one(
        self,
        filter: Mapping[str, Any],
        replacement: Mapping[str, Any],
        upsert: bool = False,
        bypass_document_validation: bool = False,
        collation: Optional[_CollationIn] = None,
        hint: Optional[_IndexKeyHint] = None,
        session: Optional[ClientSession] = None,
        let: Optional[Mapping[str, Any]] = None,
        comment: Optional[Any] = None,
    ) -> UpdateResult:
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
        update: Union[Mapping[str, Any], _Pipeline],
        upsert: bool = False,
        bypass_document_validation: bool = False,
        collation: Optional[_CollationIn] = None,
        array_filters: Optional[Sequence[Mapping[str, Any]]] = None,
        hint: Optional[_IndexKeyHint] = None,
        session: Optional[ClientSession] = None,
        let: Optional[Mapping[str, Any]] = None,
        comment: Optional[Any] = None,
    ) -> UpdateResult:
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
        update: Union[Mapping[str, Any], _Pipeline],
        upsert: bool = False,
        array_filters: Optional[Sequence[Mapping[str, Any]]] = None,
        bypass_document_validation: Optional[bool] = None,
        collation: Optional[_CollationIn] = None,
        hint: Optional[_IndexKeyHint] = None,
        session: Optional[ClientSession] = None,
        let: Optional[Mapping[str, Any]] = None,
        comment: Optional[Any] = None,
    ) -> UpdateResult:
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
        collation: Optional[_CollationIn] = None,
        hint: Optional[_IndexKeyHint] = None,
        session: Optional[ClientSession] = None,
        let: Optional[Mapping[str, Any]] = None,
        comment: Optional[Any] = None,
    ) -> DeleteResult:
        return super().delete_one(filter, collation, hint, session, let, comment)

    def delete_many(
        self,
        filter: Mapping[str, Any],
        collation: Optional[_CollationIn] = None,
        hint: Optional[_IndexKeyHint] = None,
        session: Optional[ClientSession] = None,
        let: Optional[Mapping[str, Any]] = None,
        comment: Optional[Any] = None,
    ) -> DeleteResult:
        return super().delete_many(filter, collation, hint, session, let, comment)

    def find(self, *args: Any, **kwargs: Any) -> Iterator[BsonDict]:  # type: ignore[override]
        cache_backend = cast(
            MemoryBackend, self._Collection__database.client.cache_backend
        )

        if not cache_backend.collection_can_be_cached(self.name):
            return super().find(*args, **kwargs)

        mongo_command = MongoCommand(
            self.name,
            "find",
            filter=args[0] if args else kwargs.pop("filter"),
            projection=kwargs.pop("projection"),
        )
        try:
            cached_documents = cache_backend.get_many(mongo_command=mongo_command)
        except NotCachedError:
            documents = []
            for document in Cursor(self, *args, **kwargs):
                documents.append(document)
                yield document

            cache_backend.set_many(documents=documents, mongo_command=mongo_command)
        else:
            yield from cached_documents

    def find_one(
        self,
        filter: Any | None = None,
        *args: Any,
        projection: list[str] | dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> BsonDict | None:
        local_database = cast(MemoryBackend, self.__Collection__database.local_database)

        # if self.name in local_database.:  # TODO
        #    return super().find_one(filter, *args, **kwargs)

        try:
            return cache_backend.get_one(
                mongo_command=MongoCommand(self.name, "findOne", filter, projection),
            )
        except NotCachedError:
            document = super().find_one(filter, *args, **kwargs)
            cache_backend.set_one(
                document=document,
                mongo_command=MongoCommand(self.name, "findOne", filter, projection),
            )
            return document

    def find_one_and_delete(
        self,
        filter: Mapping[str, Any],
        projection: Optional[Union[Mapping[str, Any], Iterable[str]]] = None,
        sort: Optional[_IndexList] = None,
        hint: Optional[_IndexKeyHint] = None,
        session: Optional[ClientSession] = None,
        let: Optional[Mapping[str, Any]] = None,
        comment: Optional[Any] = None,
        **kwargs: Any,
    ) -> _DocumentType:
        return super().find_one_and_delete(
            filter, projection, sort, hint, session, let, comment, **kwargs
        )

    def find_one_and_replace(
        self,
        filter: Mapping[str, Any],
        replacement: Mapping[str, Any],
        projection: Optional[Union[Mapping[str, Any], Iterable[str]]] = None,
        sort: Optional[_IndexList] = None,
        upsert: bool = False,
        return_document: bool = ReturnDocument.BEFORE,
        hint: Optional[_IndexKeyHint] = None,
        session: Optional[ClientSession] = None,
        let: Optional[Mapping[str, Any]] = None,
        comment: Optional[Any] = None,
        **kwargs: Any,
    ) -> _DocumentType:
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
        update: Union[Mapping[str, Any], _Pipeline],
        projection: Optional[Union[Mapping[str, Any], Iterable[str]]] = None,
        sort: Optional[_IndexList] = None,
        upsert: bool = False,
        return_document: bool = ReturnDocument.BEFORE,
        array_filters: Optional[Sequence[Mapping[str, Any]]] = None,
        hint: Optional[_IndexKeyHint] = None,
        session: Optional[ClientSession] = None,
        let: Optional[Mapping[str, Any]] = None,
        comment: Optional[Any] = None,
        **kwargs: Any,
    ) -> _DocumentType:
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
        session: Optional[ClientSession] = None,
        comment: Optional[Any] = None,
        **kwargs: Any,
    ) -> int:
        return super().count_documents(filter, session, comment, **kwargs)

    def estimated_document_count(
        self, comment: Optional[Any] = None, **kwargs: Any
    ) -> int:
        return super().estimated_document_count(comment, **kwargs)

    def distinct(
        self,
        key: str,
        filter: Optional[Mapping[str, Any]] = None,
        session: Optional[ClientSession] = None,
        comment: Optional[Any] = None,
        **kwargs: Any,
    ) -> list:
        return super().distinct(key, filter, session, comment, **kwargs)

    def drop(
        self,
        session: Optional[ClientSession] = None,
        comment: Optional[Any] = None,
        encrypted_fields: Optional[Mapping[str, Any]] = None,
    ) -> None:
        return super().drop(session, comment, encrypted_fields)

    def rename(
        self,
        new_name: str,
        session: Optional[ClientSession] = None,
        comment: Optional[Any] = None,
        **kwargs: Any,
    ) -> MutableMapping[str, Any]:
        return super().rename(new_name, session, comment, **kwargs)
