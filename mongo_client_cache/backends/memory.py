from collections.abc import Mapping
from typing import Any

from mongo_client_cache.backends.base import BaseBackend, CollectionConfig, MongoCommand


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
            raise NotCachedError from e
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
            self._collections[collection_name].iloc[0] = [document_id, document]
        self._quieries[collection_name].iloc[0] = [
            mongo_command.name,
            mongo_command.filter,
            mongo_command.projection,
            document_id,
        ]
