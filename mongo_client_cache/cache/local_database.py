from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from itertools import count
from threading import Thread
from typing import Any

from bson import ObjectId
from pymongo.database import Database
from pymongo.errors import PyMongoError

from mongo_client_cache.cache.exceptions import UnexpectedChangeOperationTypeError
from mongo_client_cache.cache.misc import CollectionConfig, CommandCount
from mongo_client_cache.logger import logger
from mongo_client_cache.types import (
    BsonDict,
    BsonValue,
    ChangeStreamDocument,
    CollectionName,
    JsonDict,
)


class DatabaseCache:
    __slots__ = (
        "change_stream_documents",
        "distinct_per_collection",
        "document_count_per_collection",
        "estimated_document_count_per_collection",
        "local_collections",
        "mongo_database",
        "query_to_ids_map",
        "resume_token",
        "static_collections_names",
    )

    def __init__(
        self, database: Database, config_per_collection: list[CollectionConfig]
    ) -> None:
        self.mongo_database = database
        self.static_collections_names = {
            collection_config.collection_name
            for collection_config in config_per_collection
            if collection_config.watch_change_stream is False
        }

        self.local_collections: dict[CollectionName, dict[ObjectId, BsonDict]] = {}
        self.query_to_ids_map: dict[CollectionName, dict[str, BsonDict]] = {}
        self.document_count_per_collection: dict[CollectionName, dict[str, int]] = {
            collection_config.collection_name: {}
            for collection_config in config_per_collection
        }
        self.estimated_document_count_per_collection: dict[
            CollectionName, dict[str, int]
        ] = {
            collection_config.collection_name: {}
            for collection_config in config_per_collection
        }
        self.distinct_per_collection: dict[
            CollectionName, dict[str, list[BsonValue]]
        ] = {
            collection_config.collection_name: {}
            for collection_config in config_per_collection
        }

        logger.debug(
            f"Connected to the '{database.name}' database. {self.static_collections_names=}"
        )
        self.change_stream_documents: dict[str, list[ChangeStreamDocument]] = (
            defaultdict(list)
        )

        if {
            collection_config.collection_name
            for collection_config in config_per_collection
            if collection_config.watch_change_stream is False
        }:
            Thread(target=self.watch, daemon=True).start()

    def watch(self) -> None:
        """
        https://github.com/mongodb/specifications/blob/master/source/change-streams/change-streams.rst
        https://www.mongodb.com/docs/manual/reference/change-events/#change-events
        """
        self.resume_token: Mapping[str, Any] | None = None

        max_retries = 3
        for retry_attempt in count():
            try:
                self._watch()
            except PyMongoError as error:
                # The ChangeStream encountered an unrecoverable error or the
                # resume attempt failed to recreate the cursor.
                if self.resume_token is None:
                    if retry_attempt == max_retries:
                        raise
                    logger.error(
                        "There is no usable resume token because there was a "
                        + "failure during ChangeStream initialization. "
                        + f"Target: {self.mongo_database}, {retry_attempt=}, {error!r}."
                    )

    def _watch(self) -> None:
        while True:
            pipeline: list[JsonDict] = [
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
            logger.info(f'Watching Change Stream for "{self.mongo_database.name}".')
            with self.mongo_database.watch(
                pipeline, full_document="updateLookup", resume_after=self.resume_token
            ) as stream:
                for change in stream:
                    if __debug__:
                        logger.debug(f"{change=}, {stream.resume_token=}")

                    # Use the interrupted ChangeStream's resume token to create
                    # a new ChangeStream. The new stream will continue from the
                    # last seen insert change without missing any events.
                    self.resume_token = stream.resume_token
                    continue

    def _insert(self, change: ChangeStreamDocument) -> None:
        collection_name = change["ns"]["coll"]
        self.change_stream_documents[collection_name].append(change)
        self.estimated_document_count_per_collection[collection_name] += 1
        self.document_count_per_collection[collection_name][str(CommandCount({}))] += 1
        # Invalidate all cached queries.
        del self.query_to_ids_map[collection_name]
        del self.distinct_per_collection[collection_name]

    def _update(self, change: ChangeStreamDocument) -> None:
        collection_name = change["ns"]["coll"]
        self.change_stream_documents[collection_name].append(change)
        # Invalidate all cached queries.
        del self.query_to_ids_map[collection_name]
        del self.distinct_per_collection[collection_name]

    def _replace(self, change: ChangeStreamDocument) -> None:
        collection_name = change["ns"]["coll"]
        self.change_stream_documents[collection_name].append(change)
        # Invalidate all cached queries.
        del self.query_to_ids_map[collection_name]
        del self.distinct_per_collection[collection_name]

    def _delete(self, change: ChangeStreamDocument) -> None:
        collection_name = change["ns"]["coll"]
        self.change_stream_documents[collection_name].append(change)
        self.estimated_document_count_per_collection[collection_name] -= 1
        self.document_count_per_collection[collection_name][str(CommandCount({}))] -= 1
        # Invalidate all cached queries.
        del self.query_to_ids_map[collection_name]
        del self.distinct_per_collection[collection_name]

    def _drop(self, change: ChangeStreamDocument) -> None:
        collection_name = change["ns"]["coll"]
        # Drop cached and pending documents.
        del self.local_collections[collection_name]
        del self.change_stream_documents[collection_name]
        # Invalidate all cached queries.
        del self.query_to_ids_map[collection_name]
        del self.distinct_per_collection[collection_name]

    def _drop_database(self) -> None:
        self.local_collections.clear()
        self.query_to_ids_map.clear()
        self.distinct_per_collection.clear()

    def _rename(self, change: ChangeStreamDocument) -> None:
        # TODO: What is renamed? Collection? Database?  # noqa: TD003
        raise NotImplementedError

    def _process_change_stream(self, change: ChangeStreamDocument) -> None:
        operation_type = change["operationType"]
        if operation_type == "insert":
            self._insert(change)
        elif operation_type == "update":
            self._update(change)
        elif operation_type == "replace":
            self._replace(change)
        elif operation_type == "delete":
            self._delete(change)
        elif operation_type == "drop":
            self._drop(change)
        elif operation_type == "dropDatabase":
            self._drop_database()
        elif operation_type == "rename":
            self._rename(change)
        else:
            raise UnexpectedChangeOperationTypeError(change["operationType"])
