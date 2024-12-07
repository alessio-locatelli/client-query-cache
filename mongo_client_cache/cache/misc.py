from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pymongo.cursor_shared import _Sort


@dataclass(slots=True)
class CommandFind:
    filter: Mapping[str, Any] | None = None
    projection: Iterable[str] | Mapping[str, Any] | None = None
    skip: int = 0
    limit: int = 0
    sort: _Sort | None = None

    def __post_init__(self) -> None:
        if self.filter:
            self.filter = tuple(sorted(self.filter.items()))
        elif self.filter is None:
            self.filter = {}
        if self.projection is None:
            return
        self.projection = (
            tuple(sorted(self.projection))
            if isinstance(self.projection, Iterable)
            else dict(sorted(self.projection.items()))
        )

    def __str__(self) -> str:
        return f"{self.filter},{self.skip},{self.limit},{self.sort}"


@dataclass(slots=True)
class CommandCount:
    filter: Mapping[str, Any]
    skip: int = 0
    limit: int = 0

    def __str__(self) -> str:
        return f"{self.filter or tuple(sorted(self.filter.items()))},{self.skip},{self.limit}"


command_count_empty_filter = str(CommandCount({}))


@dataclass(slots=True)
class CommandDistinct:
    key: str = field(
        kw_only=True  # "TypeError: non-default argument 'key' follows default argument".
    )
    filter: Mapping[str, Any] | None = None

    def __str__(self) -> str:
        return f"{self.filter},{self.key}"
