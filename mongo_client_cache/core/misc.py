from collections import UserDict
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from pymongo.cursor import _Sort


@dataclass(slots=True)
class CommandFind:
    collection_name: str
    filter: Any = None
    projection: Iterable[str] | Mapping[str, Any] | None = None
    skip: int = 0
    limit: int = 0
    sort: _Sort | None = None

    def __iter__(self) -> Iterator[Any]:
        yield from [self.filter, self.projection, self.skip, self.limit, self.sort]


@dataclass(slots=True)
class CommandCount:
    collection_name: str
    filter: Any = None
    skip: int = 0
    limit: int = 0

    def __iter__(self) -> Iterator[Any]:
        yield from [self.filter, self.skip, self.limit]


@dataclass(slots=True)
class CommandDistinct:
    collection_name: str
    key: str
    filter: Any = None

    def __iter__(self) -> Iterator[Any]:
        yield from [self.key, self.filter]


@dataclass(slots=True)
class CollectionConfig:
    """
    :param watch_change_stream: use `False` if you are not adding or modifying documents in this collection
    :param enable_client_side_cache: use `False` to exclude the collection from caching
    """  # noqa: E501

    collection_name: str
    watch_change_stream: bool = True
    enable_client_side_cache: bool = True

    def __post_init__(self) -> None:
        assert self.collection_name, "Collection name must be a non-empty string."
        assert isinstance(self.watch_change_stream, bool)
        assert isinstance(self.enable_client_side_cache, bool)


class LocalClient(UserDict):
    ...
