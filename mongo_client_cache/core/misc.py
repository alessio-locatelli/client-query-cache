from collections import UserDict
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal


@dataclass(slots=True)
class MongoCommand:
    collection_name: str
    name: Literal["findOne", "find"]
    filter: Any = None
    projection: list[str] | dict[str, Any] | None = None

    def __iter__(self) -> Iterator[Any]:
        yield from [
            self.collection_name,
            self.name,
            self.filter,
            self.projection,
        ]


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
