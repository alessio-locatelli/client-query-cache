from datetime import datetime
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from mongo_client_cache.core.misc import CollectionConfig

type JsonValue = int | float | str | bool | None | list["JsonValue"] | "JsonDict"  # type: ignore[valid-type]
type JsonDict = dict[str, JsonValue]  # type: ignore[valid-type]

type BsonValue = (  # type: ignore[valid-type]
    int | float | str | bool | None | list["BsonValue"] | "BsonDict" | datetime | bytes  # type: ignore[valid-type]
)
type BsonDict = dict[str, BsonValue]  # type: ignore[valid-type]


type CollectionName = str
type DatabaseName = str
type ClientSideCacheConfig = dict[DatabaseName, list[CollectionConfig]]
