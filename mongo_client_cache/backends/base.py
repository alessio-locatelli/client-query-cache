from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from functools import partial
from typing import Any, Literal

import pandas as pd

from mongo_client_cache.backends.exceptions import NotAPositiveNumberError


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
