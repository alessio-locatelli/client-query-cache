from mongo_client_cache._types import JsonDict

pipeline: list[JsonDict] = [
    {
        "$match": {
            "operationType": {
                "$in": [
                    "insert",
                    "update",
                    "replace",
                    "delete",
                    "drop",
                    "rename",
                ]
            },
        }
    },
    {
        "$project": {
            "operationType": True,
            "documentKey": True,
            "wallTime": True,
        }
    },
]
