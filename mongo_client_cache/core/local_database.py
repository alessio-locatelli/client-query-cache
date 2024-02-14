from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from functools import partial
from typing import Any, Literal
from typing import cast

import pandas as pd
from mongo_client_cache.core.exceptions import DocumentIdMissingError, NotCachedError

from mongo_client_cache.logger import logger
from mongo_client_cache.types import BsonDict, BsonValue


import pandas as pd

from mongo_client_cache.core.exceptions import NotAPositiveNumberError


@dataclass(slots=True)
class MongoCommand:
    collection: str
    name: Literal["findOne", "find"]
    filter: Any = None
    projection: list[str] | dict[str, Any] | None = None

    def __iter__(self) -> Iterator[Any]:
        yield from [self.collection, self.name, self.filter, self.projection]


@dataclass(slots=True)
class CollectionConfig:
    """
    :param watch_change_stream: use `False` if you are not adding or modifying documents in this collection
    :param change_stream_watch_interval_seconds: the default value is used
    :param enable_client_side_cache: use `False` to exclude the collection from caching
    """  # noqa: E501

    database_name: str
    collection_name: str
    watch_change_stream: bool = True
    change_stream_watch_interval_seconds: float | None = None
    enable_client_side_cache: bool = True

    def __post_init__(self) -> None:
        assert self.database_name, "Database name must be a non-empty string."
        assert self.collection_name, "Collection name must be a non-empty string."
        assert isinstance(self.watch_change_stream, bool)
        assert isinstance(self.enable_client_side_cache, bool)
        if (
            self.change_stream_watch_interval_seconds
            and self.change_stream_watch_interval_seconds <= 0
        ):
            raise NotAPositiveNumberError(
                f"{self.change_stream_watch_interval_seconds=}"
            )


class ClientSideDatabase:
    __slots__ = (
        "name",
        "collections",
        "cached_queries",
        "static_collections",
        "excluded_collections",
        "subscribed_for_change_stream",
    )

    def __init__(
        self, name: str, config_per_collection: list[CollectionConfig] | None
    ) -> None:
        self.name = name
        if config_per_collection:
            self.excluded_collections = {
                collection_config.collection_name
                for collection_config in config_per_collection
                if collection_config.enable_client_side_cache is False
            }
            self.static_collections = {
                collection_config.collection_name
                for collection_config in config_per_collection
                if collection_config.watch_change_stream is False
            }

        else:
            self.excluded_collections = set()
            self.static_collections = set()

        self.collections: dict[str, pd.DataFrame] = defaultdict(
            lambda: pd.DataFrame(columns=["_id", "document"]).set_index("_id")
        )
        self.cached_queries: dict[str, pd.DataFrame] = defaultdict(
            partial(
                pd.DataFrame,
                columns=[
                    "database_name",
                    "collection_name",
                    "command",
                    "filter",
                    "projection",
                    "documents_ids",
                ],
            )
        )
        self.subscribed_for_change_stream = False

    def _find_cached_documents_ids(self, mongo_command: MongoCommand) -> set[BsonValue]:  # type: ignore[valid-type]
        queries = self.cached_queries[mongo_command.collection]
        query = queries[
            (queries["command"] == mongo_command.name)
            & (
                queries["filter"].isna()
                if mongo_command.filter is None
                else queries["filter"] == mongo_command.filter
            )
            & (
                queries["projection"].isna()
                if mongo_command.projection is None
                else queries["projection"] == mongo_command.projection
            )
        ]
        try:
            return query.iloc[(0, -1)]
        except IndexError as e:
            logger.debug(f"Not found in cache: {mongo_command}")
            raise NotCachedError from e

    def _find_cached_document_id(self, mongo_command: MongoCommand) -> BsonValue:  # type: ignore[valid-type]
        return cast(BsonValue, self._find_cached_documents_ids(mongo_command))  # type: ignore[valid-type]

    def get_one(self, mongo_command: MongoCommand) -> BsonDict | None:
        document_id = self._find_cached_document_id(mongo_command)
        if document_id is None:
            return None
        logger.debug(f"Found in cache: {mongo_command}, {document_id=}")  # type: ignore[unreachable]
        df_collection = self.collections[mongo_command.collection]
        return df_collection.loc[document_id]["document"]

    def set_one(
        self, *, document: BsonDict | None, mongo_command: MongoCommand
    ) -> None:
        try:
            document_id = document["_id"]  # type: ignore[index]
        except TypeError:
            # The query found no documents so we have `None` instead of a document.
            document_id = None
        except KeyError:
            raise DocumentIdMissingError from KeyError
        else:
            df_collection = self.collections[mongo_command.collection]
            df_collection.loc[document_id] = [document]

        logger.debug(f"{mongo_command}, {document_id=}.")
        df_queries = self.queries[mongo_command.collection]
        df_queries.loc[len(df_queries)] = [*list(mongo_command), document_id]

    def set_many(
        self,
        *,
        documents: list[BsonDict],
        mongo_command: MongoCommand,
    ) -> None:
        logger.debug(f"{mongo_command}, {documents=}")
        if not documents:
            return
        df_collection = self.collections[mongo_command.collection]
        df_documents = pd.DataFrame(documents)
        df_documents.set_index("_id", inplace=True)  # noqa: PD002
        df_collection = df_collection.combine_first(df_documents)

        df_queries = self.queries[mongo_command.collection]
        try:
            documents_ids = [document["_id"] for document in documents]
        except KeyError:
            raise DocumentIdMissingError from KeyError
        df_queries.loc[len(df_queries)] = [*list(mongo_command), documents_ids]

    def get_many(self, mongo_command: MongoCommand) -> list[BsonDict]:
        documets_ids = self._find_cached_documents_ids(mongo_command)
        df_collection = self.collections[mongo_command.collection]
        return df_collection.loc[df_collection["_id"] in documets_ids]
