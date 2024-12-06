from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, TypedDict

from bson import ObjectId

if TYPE_CHECKING:
    from mongo_client_cache.core.misc import CollectionConfig

type JsonValue = int | float | str | bool | None | list["JsonValue"] | "JsonDict"
type JsonDict = dict[str, JsonValue]

type BsonValue = (
    int | float | str | bool | None | list["BsonValue"] | "BsonDict" | datetime | bytes
)
type BsonDict = dict[str, BsonValue]


type CollectionName = str
type DatabaseName = str
type ClientSideCacheConfig = dict[DatabaseName, list[CollectionConfig]]


class ChangeStreamDocument(TypedDict):
    _id: dict[str, str]
    operationType: str
    fullDocument: BsonDict
    ns: dict[str, str]
    documentKey: dict[str, ObjectId]
    wallTime: datetime
