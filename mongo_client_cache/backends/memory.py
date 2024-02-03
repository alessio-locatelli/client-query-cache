from collections.abc import Mapping
from typing import Any

from mongo_client_cache.backends.base import BaseBackend, CollectionConfig, MongoCommand
from mongo_client_cache.logger import logger


class NotCachedError(Exception): ...


class MemoryBackend(BaseBackend):
    __slots__ = ()

    def __init__(
        self,
        *,
        cache_only_collections: set[str] | None = None,
        config_per_collection: list[CollectionConfig] | None = None,
    ) -> None:
        super().__init__(
            cache_only_collections=cache_only_collections,
            config_per_collection=config_per_collection,
        )

    def get_one(
        self, *, collection_name: str, mongo_command: MongoCommand
    ) -> Mapping[str, Any]:
        queries = self._quieries[collection_name]
        query = queries[
            (queries["command"] == mongo_command.name)
            & (queries["filter"] == mongo_command.filter)
            & (queries["projection"] == mongo_command.projection)
        ]
        try:
            document_id = query.iloc[(0, -1)]
        except IndexError as e:
            logger.debug(f"Not found in cache: {mongo_command}, {collection_name=}.")
            raise NotCachedError from e

        logger.debug(f"Found in cache: {mongo_command}, {collection_name=}.")
        return self._collections[collection_name][document_id]["document"]

    def set_one(
        self,
        *,
        collection_name: str,
        document: Mapping[str, Any] | None,
        mongo_command: MongoCommand,
    ) -> None:
        try:
            document_id = document["_id"]  # type: ignore[index]
        except TypeError:
            # The query found no documents so we have `None` instead of a document.
            document_id = None
        else:
            df_collection = self._collections[collection_name]
            df_collection.loc[len(df_collection)] = [document_id, document]

        df_queries = self._quieries[collection_name]
        df_queries.loc[len(df_queries)] = [
            collection_name,
            mongo_command.name,
            mongo_command.filter,
            mongo_command.projection,
            document_id,
        ]
