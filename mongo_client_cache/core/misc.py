from __future__ import annotations

from collections import UserDict
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from pymongo.cursor import _Sort


@dataclass(slots=True)
class _Command:
    collection_name: str
    filter: Any = None

    def __post_init__(self) -> None:
        if self.filter:
            self.filter = tuple(sorted(self.filter.items()))


@dataclass(slots=True)
class CommandFind(_Command):
    projection: Iterable[str] | Mapping[str, Any] | None = None
    skip: int = 0
    limit: int = 0
    sort: _Sort | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.projection is None:
            return        
        self.projection = tuple(sorted(self.projection)) if isinstance(self.projection, Iterable) else dict(sorted(self.projection.items()))


@dataclass(slots=True)
class CommandCount(_Command):
    skip: int = 0
    limit: int = 0


@dataclass(slots=True)
class CommandDistinct(_Command):
    key: str = field(
        kw_only=True  # "TypeError: non-default argument 'key' follows default argument".
    )


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


class LocalClient(UserDict): ...
