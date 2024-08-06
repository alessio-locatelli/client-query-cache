from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping
from itertools import count
from threading import Thread
from typing import Any, cast

from bson import ObjectId
from pymongo.database import Database
from pymongo.errors import PyMongoError

from mongo_client_cache.core.exceptions import (
    DocumentIdMissingError,
    NotCachedError,
    UnexpectedChangeOperationTypeError,
)
from mongo_client_cache.core.misc import (
    CollectionConfig,
    CommandCount,
    CommandDistinct,
    CommandFind,
)
from mongo_client_cache.logger import logger
from mongo_client_cache.types import (
    BsonDict,
    BsonValue,
    ChangeStreamDocument,
    CollectionName,
    JsonDict,
)


class _DatabaseCache:
    __slots__ = (
        "cached_find",
        "collections_names_with_cached_documents",
        "distinct_per_collection",
        "document_count_per_collection",
        "estimated_document_count_per_collection",
        "excluded_collections_names",
        "local_collections",
        "mongo_database",
        "resume_token",
        "static_collections_names",
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

        self.local_collections: dict[CollectionName, dict[ObjectId, BsonDict]] = {}
        self.cached_find: dict[CollectionName, dict[str, BsonDict]] = {}
        self.collections_names_with_cached_documents: set[str] = set()
        self.document_count_per_collection: dict[CollectionName, dict[str, Any]] = {}
        self.estimated_document_count_per_collection: dict[CollectionName, int] = {}
        self.distinct_per_collection: dict[CollectionName, dict[str, list[BsonValue]]] = {}

    def _find_cached_documents_ids(self, collection_name: str, mongo_command: CommandFind) -> set[BsonValue]:  # type: ignore[valid-type]
        queries = self.cached_find[collection_name]
        query = queries[
            (
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
            logger.debug(f"Not found in cache: {mongo_command}, {query=}, {e!r}")
            raise NotCachedError from e

    def _find_cached_document_id(self, mongo_command: CommandFind) -> BsonValue:  # type: ignore[valid-type]
        return cast(BsonValue, self._find_cached_documents_ids(mongo_command))  # type: ignore[valid-type]

    def get_one(self, collection_name: str, mongo_command: CommandFind) -> BsonDict | None:
        document_id = self._find_cached_document_id(mongo_command)
        if document_id is None:
            return None
        logger.debug(f"Found in cache: {mongo_command}, {document_id=}")  # type: ignore[unreachable]
        df_collection = self.local_collections[collection_name]
        return df_collection.loc[document_id]["document"]

    def get_many(self, collection_name: str, mongo_command: CommandFind) -> deque[BsonDict]:
        documets_ids = self._find_cached_documents_ids(mongo_command)
        df_collection = self.local_collections[collection_name]
        return deque(df_collection.loc[df_collection["_id"] in documets_ids])

    def set_one(self, document: BsonDict | None, collection_name: str, mongo_command: CommandFind) -> None:
        try:
            document_id = document["_id"]  # type: ignore[index]
        except TypeError:
            # The query found no documents so we have `None` instead of a document.
            document_id = None
        except KeyError:
            raise DocumentIdMissingError from KeyError
        else:
            self.local_collections[collection_name][document_id] = document
            self.collections_names_with_cached_documents.add(collection_name)

        self.cached_find[collection_name][str(mongo_command)] = document_id

    def set_many(self, documents: list[BsonDict], collection_name: str, mongo_command: CommandFind) -> None:
        if not documents:
            return
        df_collection = self.local_collections[collection_name]
        df_documents = pd.DataFrame(documents)
        df_documents.set_index("_id", inplace=True)  # noqa: PD002
        self.local_collections[collection_name] = (
            df_collection.combine_first(df_documents)
        )

        df_queries = self.cached_find[mongo_command.collection_name]
        try:
            documents_ids = [document["_id"] for document in documents]
        except KeyError:
            raise DocumentIdMissingError from KeyError
        df_queries.loc[len(df_queries)] = [*list(mongo_command), documents_ids]
        self.collections_names_with_cached_documents.add(mongo_command.collection_name)

    def get_document_count(self, collection_name: str, mongo_command: CommandCount) -> int:
        try:
            return self.document_count_per_collection[mongo_command.collection_name][
                mongo_command.filter
            ][mongo_command.skip][mongo_command.limit]
        except KeyError as e:
            raise NotCachedError from e

    def set_document_count(
        self, document_count: int, collection_name: str, mongo_command: CommandCount
    ) -> None:
        self.document_count_per_collection[collection_name][
            mongo_command.filter
        ][mongo_command.skip][mongo_command.limit] = document_count

    def get_distinct(self, collection_name: str, mongo_command: CommandDistinct) -> list[BsonValue]:
        df_cached_commands = self.distinct_per_collection[collection_name]
        query = df_cached_commands[
            (df_cached_commands["key"] == mongo_command.key)
            & (
                df_cached_commands["filter"].isna()
                if mongo_command.filter is None
                else df_cached_commands["filter"] == mongo_command.filter
            )
        ]
        try:
            return query.iloc[(0, -1)]
        except IndexError as e:
            logger.debug(f"Not found in cache: {mongo_command}, {query=}, {e!r}")
            raise NotCachedError from e

    def set_distinct(
        self, distinct_values: list[BsonValue], collection_name: str, mongo_command: CommandDistinct
    ) -> None:
        self.distinct_per_collection[collection_name][mongo_command] = distinct_values


class DatabaseCache(_DatabaseCache):
    __slots__ = ("change_stream_documents",)

    def __init__(
        self, database: Database, config_per_collection: list[CollectionConfig] | None
    ) -> None:
        super().__init__(database, config_per_collection)
        logger.debug(
            f'Connected to local database "{database.name}".'
            + f"{self.excluded_collections_names=}, {self.static_collections_names=}"
        )
        self.change_stream_documents: dict[str, list[ChangeStreamDocument]] = (
            defaultdict(list)
        )
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
            # collections_names_with_cached_documents = list(
            #    self.collections_names_with_cached_documents
            # )
            # if not collections_names_with_cached_documents:
            #    time.sleep(1)
            #    continue
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
            # pipeline[0]["$match"]["ns.coll"] = {  # type: ignore[index]
            #    "$in": collections_names_with_cached_documents
            # }
            # logger.debug(
            #    f"Watching collections: {collections_names_with_cached_documents}."
            # )
            logger.info(f'Watching Change Stream for "{self.mongo_database.name}".')
            with self.mongo_database.watch(
                pipeline, full_document="updateLookup", resume_after=self.resume_token
            ) as stream:
                for change in stream:
                    logger.debug(f"{change=}, {stream.resume_token=}")

                    # Use the interrupted ChangeStream's resume token to create
                    # a new ChangeStream. The new stream will continue from the
                    # last seen insert change without missing any events.
                    self.resume_token = stream.resume_token
                    continue
                    if (
                        collections_names_with_cached_documents
                        != self.collections_names_with_cached_documents
                    ):
                        logger.info(
                            "Restarting 'watch'."
                            + f"Previously watched collections: {collections_names_with_cached_documents}, "  # noqa: E501
                            + f"Current collections with cached documents: {self.collections_names_with_cached_documents}."  # noqa: E501
                        )
                        break

    def _insert(self, change: ChangeStreamDocument) -> None:
        collection_name = change["ns"]["coll"]
        self.change_stream_documents[collection_name].append(change)
        # Invalidate all cached queries.
        del self.cached_find[collection_name]

    def _update(self, change: ChangeStreamDocument) -> None:
        collection_name = change["ns"]["coll"]
        self.change_stream_documents[collection_name].append(change)
        # Invalidate all cached queries.
        del self.cached_find[collection_name]

    def _replace(self, change: ChangeStreamDocument) -> None:
        collection_name = change["ns"]["coll"]
        self.change_stream_documents[collection_name].append(change)
        # Invalidate all cached queries.
        del self.cached_find[collection_name]

    def _delete(self, change: ChangeStreamDocument) -> None:
        collection_name = change["ns"]["coll"]
        self.change_stream_documents[collection_name].append(change)
        # Invalidate all cached queries.
        del self.cached_find[collection_name]

    def _drop(self, change: ChangeStreamDocument) -> None:
        collection_name = change["ns"]["coll"]
        # Drop cached and pending documents.
        del self.local_collections[collection_name]
        del self.change_stream_documents[collection_name]
        # Invalidate all cached queries.
        del self.cached_find[collection_name]

    def _drop_database(self, change: ChangeStreamDocument) -> None:
        self.local_collections.clear()
        self.cached_find.clear()

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
            self._drop_database(change)
        elif operation_type == "rename":
            self._rename(change)
        else:
            raise UnexpectedChangeOperationTypeError(change["operationType"])
