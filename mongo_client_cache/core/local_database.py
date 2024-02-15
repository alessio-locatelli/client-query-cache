from collections import defaultdict
from collections.abc import Mapping
from functools import partial
from threading import Thread
from typing import Any, cast

import pandas as pd
from pymongo.database import Database
from pymongo.errors import PyMongoError

from mongo_client_cache.core.exceptions import (
    DocumentIdMissingError,
    NotCachedError,
)
from mongo_client_cache.core.misc import CollectionConfig, MongoCommand
from mongo_client_cache.logger import logger
from mongo_client_cache.types import BsonDict, BsonValue, CollectionName


class ClientSideDatabase:
    __slots__ = (
        "mongo_database",
        "local_collections",
        "cached_queries",
        "static_collections_names",
        "excluded_collections_names",
        "_resume_token",
    )

    def __init__(
        self, database: Database, config_per_collection: list[CollectionConfig] | None
    ) -> None:
        self.mongo_database = database
        if config_per_collection:
            self.excluded_collections_names = {
                collection_config.collection_name
                for collection_config in config_per_collection
                if collection_config.enable_client_side_cache is False
            }
            self.static_collections_names = {
                collection_config.collection_name
                for collection_config in config_per_collection
                if collection_config.watch_change_stream is False
            }

        else:
            self.excluded_collections_names = set()
            self.static_collections_names = set()

        self.local_collections: dict[CollectionName, pd.DataFrame] = defaultdict(
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
        Thread(target=self.watch).start()

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
        df_queries = self.cached_queries[mongo_command.collection]
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

        df_queries = self.cached_queries[mongo_command.collection]
        try:
            documents_ids = [document["_id"] for document in documents]
        except KeyError:
            raise DocumentIdMissingError from KeyError
        df_queries.loc[len(df_queries)] = [*list(mongo_command), documents_ids]

    def get_many(self, mongo_command: MongoCommand) -> list[BsonDict]:
        documets_ids = self._find_cached_documents_ids(mongo_command)
        df_collection = self.collections[mongo_command.collection]
        return df_collection.loc[df_collection["_id"] in documets_ids]

    def watch(self) -> None:
        """
        https://github.com/mongodb/specifications/blob/master/source/change-streams/change-streams.rst
        https://www.mongodb.com/docs/manual/reference/change-events/#change-events
        """
        self._resume_token: Mapping[str, Any] | None = None

        retry_count = 3
        while True:
            try:
                self._watch()
            except PyMongoError as error:
                # The ChangeStream encountered an unrecoverable error or the
                # resume attempt failed to recreate the cursor.
                if self._resume_token is None:
                    if retry_count == 0:
                        raise
                    retry_count -= 1
                    logger.error(
                        "There is no usable resume token because there was a "
                        + "failure during ChangeStream initialization. "
                        + f"Target: {target}, {error!r}"
                    )

    def _watch(self) -> None:
        pipeline = [
            {
                "$match": {
                    "operationType": {
                        "$in": [
                            "insert",
                            "update",
                            "replace",
                            "delete",
                            "drop",
                            "dropDatabase",
                            "rename",
                        ]
                    },
                }
            },
            {
                "$project": {
                    "operationType": True,
                    "ns": True,
                    "fullDocument": True,
                    "documentKey": True,
                }
            },
        ]
        if self._collections:
            pipeline[0]["$match"]["$ns.coll"] = {"$in": self._collections}
        with self.database.watch(
            pipeline, full_document="updateLookup", resume_after=self._resume_token
        ) as stream:
            for change in stream:
                logger.debug(f"{change = }")

                # Use the interrupted ChangeStream's resume token to create
                # a new ChangeStream. The new stream will continue from the
                # last seen insert change without missing any events.
                self._resume_token = stream.resume_token
