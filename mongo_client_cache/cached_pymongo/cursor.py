from typing import Any, cast
from pymongo.cursor import Cursor
from mongo_client_cache.core.exceptions import NotCachedError
from mongo_client_cache.core.local_database import DatabaseCache
from mongo_client_cache.core.misc import MongoCommand

from mongo_client_cache.types import BsonDict
from mongo_client_cache.logger import logger


class CachedCursor(Cursor):
    def __init__(self, *args: Any, mongo_command: MongoCommand, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._queried_documents: list[BsonDict] = []
        self._mongo_command = mongo_command

    def next(self) -> BsonDict:
        """Advance the cursor."""
        if self._Cursor__empty:
            raise StopIteration
        if len(self._Cursor__data) or self._refresh():
            doc = self._Cursor__data.popleft()
            logger.debug(f"Found {doc}")
            self._queried_documents.append(doc)
            return doc
        raise StopIteration

    __next__ = next

    def __del__(self) -> None:
        logger.debug(f"Removing {self}...")
        if self._queried_documents:
            logger.debug(f"Saving {len(self._queried_documents)} found documents.")
            collection = self._Cursor__collection
            db = collection._Collection__database
            client = db._Database__client
            cache = cast(DatabaseCache, client._client_side_databases[db.name])
            cache.set_many(
                documents=self._queried_documents, mongo_command=self._mongo_command
            )
        return super().__del__()
