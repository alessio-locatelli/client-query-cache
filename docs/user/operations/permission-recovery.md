# Permission recovery exercise

Use this exercise on a **disposable, self-managed MongoDB 8.0+ replica set with authentication enabled**. It creates a dedicated database, role, and user. It demonstrates reads that remain available while database change-stream access is denied, then recovery in the same manager after that privilege is granted.

Use an administrator connection in `mongosh` for the setup below. Follow MongoDB's official [custom role](https://www.mongodb.com/docs/manual/reference/method/db.createRole/) and [user creation](https://www.mongodb.com/docs/manual/reference/method/db.createUser/) guidance for access and authentication setup. Atlas manages custom roles through its own interfaces; these shell role-management commands target self-managed deployments.

## Prepare a restricted reader

Choose a fresh disposable deployment where these names do not exist. In the administrator shell:

```javascript
const lab = db.getSiblingDB("client_query_cache_permission_lab");
lab.products.insertOne({ _id: "book", description: "available directly" });
lab.createRole({
  role: "cacheLabReader",
  privileges: [
    {
      resource: { db: "client_query_cache_permission_lab", collection: "" },
      actions: ["find", "listCollections", "listIndexes"],
    },
  ],
  roles: [],
});
lab.createUser({
  user: "cacheLabReader",
  pwd: passwordPrompt(),
  roles: [{ role: "cacheLabReader", db: "client_query_cache_permission_lab" }],
});
```

The role permits reads and metadata inspection but omits [`changeStream`](https://www.mongodb.com/docs/manual/reference/privilege-actions/#changestream). MongoDB's built-in `read` role already includes that action, so using `read` would not reproduce this failure.

## Observe denial and restoration

In an application environment with `client-query-cache` installed, set `MONGODB_URI` to authenticate as this new user with `authSource=client_query_cache_permission_lab`. Keep credentials in your normal secret configuration; do not print the URI. Save and run the following program:

```python
import os
from time import monotonic, sleep

from pymongo import MongoClient

from client_query_cache import CacheManager, StreamHealthStatus

database_name = "client_query_cache_permission_lab"
with MongoClient(os.environ["MONGODB_URI"]) as client, CacheManager(client) as manager:
    cached = manager.get_cached_collection(client[database_name].products)
    print(cached.find_one({"_id": "book"}))
    print(manager.stream_health_snapshot(database_name).status)
    print(manager.snapshot())
    input("Grant changeStream in the administrator shell, then press Enter: ")

    baseline_hits = manager.snapshot().hits
    deadline = monotonic() + 60
    while monotonic() < deadline:
        document = cached.find_one({"_id": "book"})
        health = manager.stream_health_snapshot(database_name).status
        snapshot = manager.snapshot()
        if health == StreamHealthStatus.HEALTHY and snapshot.hits > baseline_hits:
            print(document)
            print(health)
            print(snapshot)
            break
        sleep(0.1)
    else:
        raise SystemExit("No healthy cache hit observed within the exercise deadline")
```

The first read returns the seeded document through PyMongo. Stream startup emits a warning, health reports `startup_failed`, and the snapshot records a `stream_unavailable` bypass. No cache hit is served. This says nothing about availability during a database outage: a bypass still needs a working database connection and the underlying PyMongo operation can fail.

While the program is waiting, grant the missing privilege in the administrator shell:

```javascript
lab.grantPrivilegesToRole("cacheLabReader", [
  {
    resource: { db: "client_query_cache_permission_lab", collection: "" },
    actions: ["changeStream"],
  },
]);
```

See MongoDB's [`grantPrivilegesToRole`](https://www.mongodb.com/docs/manual/reference/method/db.grantPrivilegesToRole/) contract. Continue the program. Subsequent reads trigger retries when the startup cooldown permits; idle managers do not retry startup in the background. Successful startup restores eligibility and the repeated reads eventually record a hit. The 60-second deadline bounds this exercise; it is not a recovery guarantee. See the canonical [retry policy](deployment.md#retry-and-error-handling) and [health states](monitoring.md#bypass-reasons-and-stream-health).

## Clean up

After the program closes its manager and client, use the administrator shell to remove the exercise's user, role, and database:

```javascript
lab.dropUser("cacheLabReader");
lab.dropRole("cacheLabReader");
lab.dropDatabase();
```

For connection loss, failover, and unavailable resume history, the [recovery guide](deployment.md#retry-and-error-handling) states the behavior: unavailable streams bypass caching, resumable streams reconnect, and lost history clears affected cached data before reopening. Application reads can still fail during those disruptions. This permission exercise establishes no timing claim for them.
