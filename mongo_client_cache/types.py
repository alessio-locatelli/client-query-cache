from datetime import datetime

type JsonValue = int | float | str | bool | None | list["JsonValue"] | "JsonDict"  # type: ignore[valid-type]
type JsonDict = dict[str, JsonValue]  # type: ignore[valid-type]

type BsonValue = (  # type: ignore[valid-type]
    int | float | str | bool | None | list["BsonValue"] | "BsonDict" | datetime | bytes  # type: ignore[valid-type]
)
type BsonDict = dict[str, BsonValue]  # type: ignore[valid-type]

type CollectionName = str
