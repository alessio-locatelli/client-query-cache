from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from functools import partial
from typing import Any, Literal

import pandas as pd

from mongo_client_cache.types import CollectionName


@dataclass(slots=True)
class MongoCommand:
    collection: str
    name: Literal["findOne", "find"]
    filter: Any = None
    projection: list[str] | dict[str, Any] | None = None

    def __iter__(self) -> Iterator[Any]:
        yield from [self.collection, self.name, self.filter, self.projection]


class NotCachedError(Exception):
    ...


class NotAPositiveNumberError(Exception):
    ...


@dataclass(slots=True)
class CollectionConfig:
    """
    :param watch_change_stream: use `False` if you are not adding or modifying documents in this collection
    :param pause_change_stream_if_idle: pause "watch" until a command is called on a collection
    :param change_stream_watch_interval_seconds: the default value is used
    :param enable_client_side_cache: use `False` to exclude the collection from caching
    """  # noqa: E501

    name: CollectionName
    watch_change_stream: bool = True
    pause_change_stream_if_idle: float | None = None
    change_stream_watch_interval_seconds: float | None = None
    enable_client_side_cache: bool = True

    def __post_init__(self) -> None:
        assert self.name, "Collection name must be a non-empty string."
        assert isinstance(self.watch_change_stream, bool)
        assert isinstance(self.enable_client_side_cache, bool)
        if self.pause_change_stream_if_idle and self.pause_change_stream_if_idle <= 0:
            raise NotAPositiveNumberError(f"{self.pause_change_stream_if_idle=}")
        if (
            self.change_stream_watch_interval_seconds
            and self.change_stream_watch_interval_seconds <= 0
        ):
            raise NotAPositiveNumberError(
                f"{self.change_stream_watch_interval_seconds=}"
            )


def _initialize_empty_collection_df() -> pd.DataFrame:
    collection_df = pd.DataFrame(columns=["_id", "document"])
    collection_df.set_index("_id", inplace=True)  # noqa: PD002
    return collection_df


class BaseBackend:
    __slots__ = (
        "_cache_only_collections",
        "_collections",
        "_queries",
        "_config_per_collection",
        "_do_not_cache_collections",
    )

    def __init__(
        self,
        *,
        cache_only_collections: set[str] | None = None,
        config_per_collection: list[CollectionConfig] | None = None,
    ) -> None:
        if cache_only_collections:
            assert all(name for name in cache_only_collections)
        self._cache_only_collections = cache_only_collections
        self._config_per_collection = config_per_collection
        if config_per_collection:
            self._do_not_cache_collections = {
                collection_config.name
                for collection_config in config_per_collection
                if collection_config.enable_client_side_cache is False
            }
        else:
            self._do_not_cache_collections = set()

        self._collections: dict[CollectionName, pd.DataFrame] = defaultdict(
            _initialize_empty_collection_df
        )
        self._queries: dict[CollectionName, pd.DataFrame] = defaultdict(
            partial(
                pd.DataFrame,
                columns=[
                    "collection_name",
                    "command",
                    "filter",
                    "projection",
                    "documents_ids",
                ],
            )
        )

    def collection_can_be_cached(self, collection_name: str) -> bool:
        if self._cache_only_collections:
            return collection_name in self._cache_only_collections
        if self._do_not_cache_collections:
            return collection_name not in self._do_not_cache_collections
        return True
