# mongodb-client-cache

A MongoDB client-side cache for `pymongo`, in early development.

---

## Status

This is a pre-release library with no cached reads or writes implemented yet. `CacheManager` wraps a `pymongo.MongoClient` you construct and own, and its database/collection facades expose the wrapped PyMongo object through `.raw` for every operation:

```python
from pymongo import MongoClient

from mongo_client_cache import CacheManager

with MongoClient("mongodb://localhost:27017") as client:
    manager = CacheManager(client)
    collection = manager["my_database"]["my_collection"]
    collection.raw.insert_one({"_id": "example", "value": 42})
```

See [`docs/migration.md`](docs/migration.md) for what changed since the earlier prototype.

## Development

See the [development environment guide](docs/development.md).
