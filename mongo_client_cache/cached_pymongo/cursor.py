from collections import deque
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any, cast, override

from pymongo import CursorType
from pymongo.client_session import ClientSession
from pymongo.cursor import Cursor, _Hint, _Sort
from pymongo.typings import _CollationIn

from mongo_client_cache.core.exceptions import NotCachedError
from mongo_client_cache.core.local_database import DatabaseCache
from mongo_client_cache.core.misc import CommandFind
from mongo_client_cache.logger import logger
from mongo_client_cache.types import BsonDict

if TYPE_CHECKING:
    from mongo_client_cache.cached_pymongo.collection import CachedCollection


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
        max: _Sort | None = None,  # noqa: A002
        min: _Sort | None = None,  # noqa: A002
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
        self._queried_documents: list[BsonDict] = []
        db = collection._Collection__database
        client = db._Database__client
        cache = cast(DatabaseCache, client._client_side_databases[db.name])
        self._mongo_command = CommandFind(
            collection.name, filter, projection, skip, limit, sort
        )
        try:
            self._cached_documents: deque | None = cache.get_many(self._mongo_command)
        except NotCachedError:
            self._cached_documents = None

    @override
    def next(self) -> BsonDict:
        collection = self._Cursor__collection  # type: ignore[attr-defined]
        db = collection._Collection__database
        client = db._Database__client
        cache = cast(DatabaseCache, client._client_side_databases[db.name])

        if collection.name in cache.excluded_collections_names:
            return super().next()

        if self._cached_documents is None:
            if self._Cursor__empty:  # type: ignore[attr-defined]
                raise StopIteration
            if len(self._Cursor__data) or self._refresh():  # type: ignore[attr-defined]
                doc = self._Cursor__data.popleft()  # type: ignore[attr-defined]
                logger.debug(f"Found {doc}")
                self._queried_documents.append(doc)
                return doc
            raise StopIteration

        try:
            return self._cached_documents.popleft()
        except IndexError as e:
            raise StopIteration from e

    __next__ = next

    @override
    def __del__(self) -> None:
        logger.debug(f"Destroying {self}...")
        if self._queried_documents:
            logger.debug(f"Saving {len(self._queried_documents)} found documents.")
            collection = self._Cursor__collection  # type: ignore[attr-defined]
            db = collection._Collection__database
            client = db._Database__client
            cache = cast(DatabaseCache, client._client_side_databases[db.name])
            cache.set_many(self._queried_documents, self._mongo_command)
        return super().__del__()
