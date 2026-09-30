# /// script
# requires-python = ">=3.14.6"
# dependencies = ["client-query-cache", "requests-cache>=1.3.3"]
#
# [tool.uv.sources]
# client-query-cache = { path = "..", editable = true }
# ///

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread
from time import monotonic, sleep
from typing import TYPE_CHECKING, Any, Self

from pymongo import MongoClient
from requests_cache import CachedSession
from requests_cache.backends.base import BaseCache
from requests_cache.backends.mongodb import MongoCache, MongoDict
from requests_cache.serializers.preconf import bson_document_serializer

from client_query_cache import CacheManager

if TYPE_CHECKING:
    from collections.abc import Iterator

    from requests_cache.serializers import SerializerType

    from client_query_cache import CacheCore

DEFAULT_MONGODB_URI = "mongodb://localhost:27017/?directConnection=true"
DATABASE_NAME = "client_query_cache_example_requests_cache"
REPEATED_REQUESTS = 5
INVALIDATION_TIMEOUT_SECONDS = 5.0
INVALIDATION_POLL_INTERVAL_SECONDS = 0.05


class CachedMongoDict(MongoDict):
    def __init__(
        self,
        cache_manager: CacheManager[dict[str, Any]],
        db_name: str,
        collection_name: str,
        *,
        serializer: SerializerType | None,
        decode_content: bool = False,
    ) -> None:
        super().__init__(
            db_name,
            collection_name=collection_name,
            connection=cache_manager.client,
            serializer=serializer,
            decode_content=decode_content,
        )
        self.cached_collection = cache_manager.cached(self.collection)

    def __getitem__(self, key: str) -> object:
        document = self.cached_collection.find_one({"_id": key})
        if document is None:
            raise KeyError(key)
        try:
            value = document["data"]
        except KeyError:
            value = document
        return self.deserialize(key, value)

    def __iter__(self) -> Iterator[str]:
        for document in self.cached_collection.find({}, {"_id": True}):
            yield document["_id"]

    def __len__(self) -> int:
        return self.cached_collection.estimated_document_count()


class CachedMongoCache(MongoCache):
    def __init__(
        self,
        cache_manager: CacheManager[dict[str, Any]],
        db_name: str = "http_cache",
        *,
        decode_content: bool = True,
    ) -> None:
        BaseCache.__init__(self, cache_name=db_name)
        self.responses = CachedMongoDict(
            cache_manager,
            db_name,
            "responses",
            serializer=bson_document_serializer,
            decode_content=decode_content,
        )
        self.redirects = CachedMongoDict(
            cache_manager, db_name, "redirects", serializer=None
        )


class OriginHandler(BaseHTTPRequestHandler):
    server: OriginServer

    def do_GET(self) -> None:
        body = json.dumps({"origin_hit": self.server.record_hit()}).encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


class OriginServer(ThreadingHTTPServer):
    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), OriginHandler)
        self._hits = 0
        self._hits_lock = Lock()
        self._thread = Thread(target=self.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}/item"

    @property
    def hits(self) -> int:
        with self._hits_lock:
            return self._hits

    def record_hit(self) -> int:
        with self._hits_lock:
            self._hits += 1
            return self._hits

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.shutdown()
        self._thread.join()
        self.server_close()


def run_scenario(
    session: CachedSession, origin: OriginServer, cache_core: CacheCore
) -> None:
    url = origin.url

    session.get(url).raise_for_status()
    if origin.hits != 1:
        message = f"expected 1 origin hit after the first request, got {origin.hits}"
        raise SystemExit(message)

    hits_before = cache_core.snapshot().hits
    for _ in range(REPEATED_REQUESTS):
        session.get(url).raise_for_status()
    cache_hits = cache_core.snapshot().hits - hits_before
    if origin.hits != 1:
        message = f"repeated requests reached the origin: {origin.hits} origin hits"
        raise SystemExit(message)
    if cache_hits < REPEATED_REQUESTS - 1:
        message = (
            f"no cache hits for repeated storage reads: expected at least "
            f"{REPEATED_REQUESTS - 1}, got {cache_hits}"
        )
        raise SystemExit(message)

    started = monotonic()
    session.cache.delete(urls=[url])
    while session.cache.contains(url=url):
        if monotonic() - started >= INVALIDATION_TIMEOUT_SECONDS:
            message = (
                f"invalidation not observed: the deleted response was still cached "
                f"after {INVALIDATION_TIMEOUT_SECONDS:.0f} s"
            )
            raise SystemExit(message)
        sleep(INVALIDATION_POLL_INTERVAL_SECONDS)
    invalidation_ms = (monotonic() - started) * 1000

    session.get(url).raise_for_status()
    if origin.hits != 2:
        message = f"expected 2 origin hits after invalidation, got {origin.hits}"
        raise SystemExit(message)

    snapshot = cache_core.snapshot()
    print(f"origin hits: {origin.hits}")
    print(f"invalidation observed after: {invalidation_ms:.0f} ms")
    print(
        f"cache hits: {snapshot.hits}, misses: {snapshot.misses}, "
        f"bypasses: {snapshot.bypasses}"
    )


def main() -> None:
    mongodb_uri = os.getenv("MONGODB_URI", DEFAULT_MONGODB_URI)
    with MongoClient[dict[str, Any]](mongodb_uri) as client:
        client.drop_database(DATABASE_NAME)
        with (
            CacheManager(client) as cache_manager,
            OriginServer() as origin,
            CachedSession(
                backend=CachedMongoCache(cache_manager, DATABASE_NAME),
                autoclose=False,
            ) as session,
        ):
            run_scenario(session, origin, cache_manager.cache_core)


if __name__ == "__main__":
    main()
