# /// script
# requires-python = ">=3.14"
# dependencies = ["client-query-cache", "Eve>=2.3.1"]
#
# [tool.uv.sources]
# client-query-cache = { path = "..", editable = true }
# ///

import os
from time import monotonic, sleep
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from eve import Eve  # type: ignore[import-untyped]
from eve.auth import BasicAuth  # type: ignore[import-untyped]
from eve.io.mongo import Mongo  # type: ignore[import-untyped]
from flask import has_request_context, request
from pymongo import MongoClient

from client_query_cache import CacheManager

if TYPE_CHECKING:
    from flask.testing import FlaskClient

DATABASE_NAME = "client_query_cache_example_eve"
DEFAULT_MONGODB_URI = "mongodb://localhost:27017/?directConnection=true"
PAGE_URL = '/items?sort=-rank&max_results=1&page=2&projection={"name":1,"rank":1}'


class ReadThroughCollection:
    def __init__(self, manager: CacheManager[dict[str, Any]], name: str) -> None:
        self.raw = manager.client[DATABASE_NAME][name]
        self.cached = manager.get_cached_collection(self.raw)

    def __getattr__(self, name: str) -> object:
        if (
            name in {"find", "find_one", "count_documents"}
            and has_request_context()
            and request.method in {"GET", "HEAD"}
        ):
            return getattr(self.cached, name)
        return getattr(self.raw, name)


class ReadThroughDatabase:
    def __init__(self, manager: CacheManager[dict[str, Any]]) -> None:
        self.manager = manager

    def __getitem__(self, name: str) -> ReadThroughCollection:
        return ReadThroughCollection(self.manager, name)


class CachedMongo(Mongo):  # type: ignore[misc]
    def init_app(self, app: Eve) -> None:
        super().init_app(app)
        manager = app.config["CACHE_MANAGER"]
        self.driver["MONGO"] = SimpleNamespace(
            cx=manager.client, db=ReadThroughDatabase(manager)
        )


class OwnerAuth(BasicAuth):  # type: ignore[misc]
    def check_auth(
        self,
        username: str,
        password: str,
        _allowed_roles: tuple[str, ...] | None,
        _resource: str,
        _method: str,
    ) -> bool:
        # pragma: allowlist nextline secret
        if username not in {"alice", "bob"} or password != "example":  # noqa: S105 -- public demo credentials
            return False
        self.set_request_auth_value(username)
        return True


def checked_json(
    http: FlaskClient, url: str, *, owner: str = "alice"
) -> dict[str, Any]:
    response = http.get(url, auth=(owner, "example"))
    if response.status_code != 200:
        message = f"GET {url} failed with status {response.status_code}"
        raise SystemExit(message)
    return response.json  # type: ignore[return-value]


def check_page(http: FlaskClient) -> dict[str, Any]:
    page = checked_json(http, PAGE_URL)
    items = page["_items"]
    if len(items) != 1 or items[0]["name"] != "middle" or items[0]["rank"] != 2:
        message = f"sorting or page selection changed: {page}"
        raise SystemExit(message)
    if "description" in items[0] or "owner" in items[0]:
        raise SystemExit("client projection was not preserved")
    if page["_meta"] != {"page": 2, "max_results": 1, "total": 3}:
        raise SystemExit("pagination count or authorization filtering changed")
    if "next" not in page["_links"] or "prev" not in page["_links"]:
        raise SystemExit("pagination response links were not preserved")
    if "_etag" not in items[0] or "_updated" not in items[0]:
        raise SystemExit("item response metadata was not preserved")
    return items[0]  # type: ignore[no-any-return]


def patch_consecutively(http: FlaskClient, item_url: str, etag: str) -> None:
    for name in ("updated", "final"):
        response = http.patch(
            item_url,
            json={"name": name},
            headers={"If-Match": etag},
            auth=("alice", "example"),
        )
        if response.status_code != 200:
            message = f"consecutive PATCH failed with status {response.status_code}"
            raise SystemExit(message)
        mutation: dict[str, Any] = response.json  # type: ignore[assignment]
        etag = mutation["_etag"]


def run_scenario(http: FlaskClient, manager: CacheManager[dict[str, Any]]) -> None:
    for owner, name, rank in (
        ("alice", "lowest", 1),
        ("alice", "middle", 2),
        ("alice", "highest", 3),
        ("bob", "private", 4),
    ):
        response = http.post(
            "/items",
            json={"name": name, "rank": rank, "description": "private note"},
            auth=(owner, "example"),
        )
        if response.status_code != 201:
            raise SystemExit("Eve failed to create the example items")

    hits_before = manager.snapshot().hits
    for _ in range(5):
        selected = check_page(http)
    if manager.snapshot().hits - hits_before < 8:
        raise SystemExit("no cache hits for repeated page and count reads")
    item_url = f"/items/{selected['_id']}"
    hits_before = manager.snapshot().hits
    for _ in range(5):
        item = checked_json(http, item_url)
        if item["name"] != "middle":
            raise SystemExit("item lookup did not preserve the document")
    if manager.snapshot().hits - hits_before < 4:
        raise SystemExit("no cache hits for repeated item reads")
    if http.get(item_url, auth=("bob", "example")).status_code != 404:
        raise SystemExit("item authorization filter was not preserved")
    bob_page = checked_json(http, "/items", owner="bob")
    if bob_page["_meta"]["total"] != 1 or bob_page["_items"][0]["name"] != "private":
        raise SystemExit("cached reads did not isolate the owners")

    reads_before = manager.snapshot()
    patch_consecutively(http, item_url, item["_etag"])
    reads_after = manager.snapshot()
    if (reads_after.hits, reads_after.misses, reads_after.bypasses) != (
        reads_before.hits,
        reads_before.misses,
        reads_before.bypasses,
    ):
        raise SystemExit("mutation precondition reads used the cache")
    started = monotonic()
    while True:
        page = checked_json(http, PAGE_URL)
        updated_item = checked_json(http, item_url)
        if page["_items"][0]["name"] == updated_item["name"] == "final":
            break
        if monotonic() - started >= 5:
            raise SystemExit("invalidation not observed for the page and item reads")
        sleep(0.05)
    snapshot = manager.snapshot()
    print("item name changed: middle -> updated -> final")
    print(f"invalidation observed after: {(monotonic() - started) * 1000:.0f} ms")
    print(
        f"cache hits: {snapshot.hits}, misses: {snapshot.misses}, "
        f"bypasses: {snapshot.bypasses}"
    )


def main() -> None:
    mongodb_uri = os.getenv("MONGODB_URI", DEFAULT_MONGODB_URI)
    with MongoClient[dict[str, Any]](mongodb_uri, tz_aware=True) as client:
        client.drop_database(DATABASE_NAME)
        with CacheManager(client) as manager:
            app = Eve(
                settings={
                    "CACHE_MANAGER": manager,
                    "MONGO_DBNAME": DATABASE_NAME,
                    "RESOURCE_METHODS": ["GET", "POST"],
                    "ITEM_METHODS": ["GET", "PATCH"],
                    "AUTH_FIELD": "owner",
                    "DOMAIN": {
                        "items": {
                            "mongo_write_concern": {"w": "majority"},
                            "schema": {
                                "name": {"type": "string", "required": True},
                                "rank": {"type": "integer", "required": True},
                                "description": {"type": "string"},
                            },
                        }
                    },
                },
                data=CachedMongo,
                auth=OwnerAuth,
            )
            with app.test_client() as http:
                run_scenario(http, manager)


if __name__ == "__main__":
    main()
