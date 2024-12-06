from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TypedDict

from bson import ObjectId

type JsonValue = int | float | str | bool | list["JsonValue"] | "JsonDict" | None
type JsonDict = dict[str, JsonValue]

type BsonValue = (
    int | float | str | bool | list["BsonValue"] | "BsonDict" | datetime | bytes | None
)
type BsonDict = dict[str, BsonValue]


type CollectionName = str
type DatabaseName = str


@dataclass(slots=True)
class CollectionConfig:
    """
    :param watch_change_stream: Use `False` if you are not adding or modifying documents in this collection.
    """  # noqa: E501

    watch_change_stream: bool = True

    def __post_init__(self) -> None:
        assert isinstance(self.watch_change_stream, bool)


type ClientSideCacheConfig = dict[DatabaseName, dict[CollectionName, CollectionConfig]]


class ChangeStreamDocument(TypedDict):
    _id: dict[str, str]
    operationType: str
    fullDocument: BsonDict
    ns: dict[str, str]
    documentKey: dict[str, ObjectId]
    wallTime: datetime
