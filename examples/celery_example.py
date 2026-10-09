# /// script
# requires-python = ">=3.14"
# dependencies = ["client-query-cache", "celery>=5.6.2"]
#
# [tool.uv.sources]
# client-query-cache = { path = "..", editable = true }
# ///

import os
from time import monotonic, sleep
from typing import Any

from celery import Celery, states  # type: ignore[import-untyped]
from celery.backends.mongodb import MongoBackend  # type: ignore[import-untyped]
from pymongo import MongoClient

from client_query_cache import CacheManager

DATABASE_NAME = "client_query_cache_example_celery"
DEFAULT_MONGODB_URI = "mongodb://localhost:27017/?directConnection=true"
TASK_ID = "example-task"


class CachedMongoBackend(MongoBackend):  # type: ignore[misc]
    def __init__(
        self, app: Celery, cache_manager: CacheManager[dict[str, Any]]
    ) -> None:
        self.cache_manager = cache_manager
        super().__init__(app=app)
        self.database_name = DATABASE_NAME
        self.cached_collection = cache_manager.get_cached_collection(self.collection)

    def _get_connection(self) -> MongoClient[dict[str, Any]]:
        return self.cache_manager.client

    def _get_task_meta_for(self, task_id: str) -> dict[str, Any]:
        document = self.cached_collection.find_one({"_id": task_id})
        if document is None:
            return {"status": states.PENDING, "result": None}
        metadata = {
            "task_id": document["_id"],
            "status": document["status"],
            "result": self.decode(document["result"]),
            "date_done": document["date_done"],
            "traceback": document["traceback"],
            "children": document["children"],
        }
        if self.app.conf.find_value_for_key("extended", "result"):
            for field in ("name", "args", "queue", "kwargs", "worker", "retries"):
                metadata[field] = document[field]
        return self.meta_from_decoded(metadata)  # type: ignore[no-any-return]


def poll_unfinished_task(backend: CachedMongoBackend) -> None:
    for _ in range(5):
        metadata = backend.get_task_meta(TASK_ID, cache=False)
        if metadata["status"] != states.STARTED:
            message = "unfinished task polling returned an unexpected state"
            raise SystemExit(message)


def main() -> None:
    mongodb_uri = os.getenv("MONGODB_URI", DEFAULT_MONGODB_URI)
    with MongoClient[dict[str, Any]](mongodb_uri) as client:
        client.drop_database(DATABASE_NAME)
        with CacheManager(client) as manager, Celery("cache-example") as app:
            backend = CachedMongoBackend(app, manager)
            backend.store_result(TASK_ID, None, states.STARTED)
            # Sample before the polling workload.
            hits_before = manager.snapshot().hits
            poll_unfinished_task(backend)
            if manager.snapshot().hits - hits_before < 4:
                raise SystemExit("no cache hits for repeated unfinished-task polling")
            backend.store_result(TASK_ID, {"answer": 42}, states.SUCCESS)
            started = monotonic()
            while True:
                metadata = backend.get_task_meta(TASK_ID, cache=False)
                if metadata["status"] == states.SUCCESS:
                    break
                if monotonic() - started >= 5:
                    raise SystemExit("invalidation not observed for the completed task")
                sleep(0.05)
            if metadata["result"] != {"answer": 42}:
                raise SystemExit("completed task result was not decoded correctly")
            snapshot = manager.snapshot()
            print(
                f"task state: {metadata['status']}, task result: {metadata['result']}"
            )
            invalidation_ms = (monotonic() - started) * 1000
            print(f"invalidation observed after: {invalidation_ms:.0f} ms")
            print(
                f"cache hits: {snapshot.hits}, misses: {snapshot.misses}, "
                f"bypasses: {snapshot.bypasses}"
            )


if __name__ == "__main__":
    main()
