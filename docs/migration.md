# Migrating to `client-query-cache`

The package and import names changed. Update the dependency and imports when upgrading:

| Before               | Now                  |
| -------------------- | -------------------- |
| `mongo-client-cache` | `client-query-cache` |
| `mongo_client_cache` | `client_query_cache` |

Install the renamed distribution with `pip install client-query-cache`. Synchronous imports use
`client_query_cache`; asyncio imports use `client_query_cache.asynchronous`:

```python
from pymongo import MongoClient

from client_query_cache import CacheManager

with (
    MongoClient("mongodb://localhost:27017") as client,
    CacheManager(client) as manager,
):
    collection = manager["my_database"]["my_collection"]
    collection.raw.insert_one({"_id": "example", "value": 42})
    document = collection.find_one({"_id": "example"})
```

For asyncio clients, import the same facade names from the asynchronous package:

```python
from client_query_cache.asynchronous import CacheManager
```

The old `mongo_client_cache` import path is unavailable after the rename; it is not provided as a
compatibility alias. See the [README](../README.md) for the current API and caching behavior.
