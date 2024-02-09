from typing import cast

import pandas as pd

from mongo_client_cache.backends.base import BaseBackend, MongoCommand, NotCachedError
from mongo_client_cache.logger import logger
from mongo_client_cache.types import BsonDict, BsonValue


class MemoryBackend(BaseBackend):
    __slots__ = ()

    def _find_cached_documents_ids(self, mongo_command: MongoCommand) -> set[BsonValue]:  # type: ignore[valid-type]
        queries = self._queries[mongo_command.collection]
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
        df_collection = self._collections[mongo_command.collection]
        return df_collection.loc[document_id]["document"]

    def set_one(
        self, *, document: BsonDict | None, mongo_command: MongoCommand
    ) -> None:
        try:
            document_id = document["_id"]  # type: ignore[index]
        except TypeError:
            # The query found no documents so we have `None` instead of a document.
            document_id = None
        else:
            df_collection = self._collections[mongo_command.collection]
            df_collection.loc[document_id] = [document]

        logger.debug(f"{mongo_command}, {document_id=}.")
        df_queries = self._queries[mongo_command.collection]
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
        df_collection = self._collections[mongo_command.collection]
        df_documents = pd.DataFrame(documents)
        df_documents.set_index("_id", inplace=True)  # noqa: PD002
        df_collection = df_collection.combine_first(df_documents)

        df_queries = self._queries[mongo_command.collection]
        df_queries.loc[len(df_queries)] = [
            *list(mongo_command),
            {document["_id"] for document in documents},
        ]

    def get_many(self, mongo_command: MongoCommand) -> list[BsonDict]:
        documets_ids = self._find_cached_documents_ids(mongo_command)
        df_collection = self._collections[mongo_command.collection]
        return df_collection.loc[df_collection["_id"] in documets_ids]
