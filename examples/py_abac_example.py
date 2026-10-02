# /// script
# requires-python = ">=3.14.6"
# dependencies = ["client-query-cache", "py-abac>=0.4.1"]
#
# [tool.uv.sources]
# client-query-cache = { path = "..", editable = true }
# ///

import os
from time import monotonic, sleep
from typing import TYPE_CHECKING, Any, cast

from py_abac import PDP, AccessRequest, Policy  # type: ignore[import-untyped]
from py_abac.storage.mongo import MongoStorage  # type: ignore[import-untyped]
from py_abac.storage.mongo.model import PolicyModel  # type: ignore[import-untyped]
from pymongo import MongoClient

from client_query_cache import CacheManager

if TYPE_CHECKING:
    from collections.abc import Iterator

DATABASE_NAME = "client_query_cache_example_py_abac"
DEFAULT_MONGODB_URI = "mongodb://localhost:27017/?directConnection=true"
POLICY_ID = "read-policy"


class CachedMongoStorage(MongoStorage):  # type: ignore[misc]
    def __init__(self, manager: CacheManager[dict[str, Any]]) -> None:
        super().__init__(manager.client, db_name=DATABASE_NAME)
        self.cached_collection = manager.cached(self.collection)

    def get(self, uid: str) -> Policy | None:
        document = self.cached_collection.find_one(uid)
        if not document:
            return None
        return cast("Policy", PolicyModel.from_doc(document).to_policy())

    def get_all(  # pytriage: TR4 -- upstream storage method name
        self, limit: int, offset: int
    ) -> Iterator[Policy]:
        self._check_limit_and_offset(limit, offset)
        for document in self.cached_collection.find({}, limit=limit, skip=offset):
            yield PolicyModel.from_doc(document).to_policy()

    def get_for_target(  # pytriage: TR4 -- upstream storage method name
        self, subject_id: str, resource_id: str, action_id: str
    ) -> Iterator[Policy]:
        pipeline = PolicyModel.get_aggregate_pipeline(
            subject_id, resource_id, action_id
        )
        for document in self.cached_collection.aggregate(pipeline):
            yield PolicyModel.from_doc(document).to_policy()


def main() -> None:
    mongodb_uri = os.getenv("MONGODB_URI", DEFAULT_MONGODB_URI)
    with MongoClient[dict[str, Any]](mongodb_uri) as client:
        client.drop_database(DATABASE_NAME)
        with CacheManager(client) as manager:
            storage = CachedMongoStorage(manager)
            policy = Policy.from_json(
                {
                    "uid": POLICY_ID,
                    "description": "Allow Alice to read the document",
                    "effect": "allow",
                    "rules": {},
                    "targets": {
                        "subject_id": "alice",
                        "resource_id": "document",
                        "action_id": "read",
                    },
                    "priority": 0,
                }
            )
            storage.add(policy)
            request = AccessRequest.from_json(
                {
                    "subject": {"id": "alice", "attributes": {}},
                    "resource": {"id": "document", "attributes": {}},
                    "action": {"id": "read", "attributes": {}},
                    "context": {},
                }
            )
            pdp = PDP(storage)
            for shape in ("get", "get_all", "get_for_target"):
                hits_before = manager.snapshot().hits
                for _ in range(5):
                    if shape == "get":
                        retrieved = storage.get(POLICY_ID)
                        policies = () if retrieved is None else (retrieved,)
                    elif shape == "get_all":
                        policies = tuple(storage.get_all(limit=1, offset=0))
                    else:
                        policies = tuple(
                            storage.get_for_target("alice", "document", "read")
                        )
                    if len(policies) != 1 or policies[0].uid != POLICY_ID:
                        message = f"policy retrieval failed for {shape}"
                        raise SystemExit(message)
                hits = manager.snapshot().hits - hits_before
                if hits < 4:
                    message = f"no cache hits for {shape}"
                    raise SystemExit(message)
                print(f"{shape} cache hits: {hits}")
            if not pdp.is_allowed(request):
                raise SystemExit("allow policy did not authorize the request")
            policy.effect = "deny"
            storage.update(policy)
            started = monotonic()
            while pdp.is_allowed(request):
                if monotonic() - started >= 5:
                    raise SystemExit("invalidation not observed for the deny policy")
                sleep(0.05)
            snapshot = manager.snapshot()
            print("authorization changed: allow -> deny")
            invalidation_ms = (monotonic() - started) * 1000
            print(f"invalidation observed after: {invalidation_ms:.0f} ms")
            print(
                f"cache hits: {snapshot.hits}, misses: {snapshot.misses}, "
                f"bypasses: {snapshot.bypasses}"
            )


if __name__ == "__main__":
    main()
