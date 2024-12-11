from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any, override

from bson.typings import _DocumentType
from pymongo import CursorType
from pymongo.client_session import ClientSession
from pymongo.cursor import Cursor
from pymongo.cursor_shared import _Hint, _Sort
from pymongo.typings import _CollationIn

from mongo_client_cache.cache import CommandFind

if TYPE_CHECKING:
    from mongo_client_cache._types import BsonDict
    from mongo_client_cache.synchronous.collection import CachedCollection


class CachedCursor(Cursor):
    @override
    def __init__(
        self,
        collection: CachedCollection,
        filter: Mapping[str, Any] | None = None,
        projection: Mapping[str, Any] | Iterable[str] | None = None,
        skip: int = 0,
        limit: int = 0,
        no_cursor_timeout: bool = False,
        cursor_type: int = CursorType.NON_TAILABLE,
        sort: _Sort | None = None,
        allow_partial_results: bool = False,
        oplog_replay: bool = False,
        batch_size: int = 0,
        collation: _CollationIn | None = None,
        hint: _Hint | None = None,
        max_scan: int | None = None,
        max_time_ms: int | None = None,
        max: _Sort | None = None,
        min: _Sort | None = None,
        return_key: bool | None = None,
        show_record_id: bool | None = None,
        snapshot: bool | None = None,
        comment: Any | None = None,
        session: ClientSession | None = None,
        allow_disk_use: bool | None = None,
        let: bool | None = None,
    ) -> None:
        super().__init__(
            collection,
            filter,
            projection,
            skip,
            limit,
            no_cursor_timeout,
            cursor_type,
            sort,
            allow_partial_results,
            oplog_replay,
            batch_size,
            collation,
            hint,
            max_scan,
            max_time_ms,
            max,
            min,
            return_key,
            show_record_id,
            snapshot,
            comment,
            session,
            allow_disk_use,
            let,
        )
        self._query = str(CommandFind(filter, projection, skip, limit, sort))
        try:
            self._cached_documents_ids = collection._cache.query_to_ids_map[self._query]
        except KeyError:
            self._cached_documents_ids = None

    @override
    def next(self) -> BsonDict:
        if self._cached_documents_ids is None:
            doc = super().next()
            _id = doc["_id"]
            self.collection._cache.query_to_ids_map[self._query].append(_id)
            self.collection._cache.documents[_id] = doc
            return doc
        try:
            _id = self._cached_documents_ids.pop()
        except IndexError:
            raise StopIteration
        else:
            return self.collection._cache.documents[_id]

    @override
    def to_list(self, length: int | None = None) -> list[_DocumentType]:
        if self._cached_documents_ids is None:
            docs = super().to_list(length)
            self.collection._cache.documents.update({d["_id"]: d for d in docs})
            return docs
        return [self.collection._cache.documents[_id] for _id in self._cached_documents_ids]
