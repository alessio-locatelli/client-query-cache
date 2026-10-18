# /// script
# requires-python = ">=3.14"
# dependencies = ["client-query-cache", "fastapi>=0.143.0", "granian==2.8.4"]
#
# [tool.uv.sources]
# client-query-cache = { path = "..", editable = true }
# ///

import argparse
import json
import multiprocessing
import os
import re
import signal
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from functools import partial
from time import monotonic, sleep
from typing import TYPE_CHECKING, Annotated, TypedDict

from fastapi import FastAPI, HTTPException, Request
from granian import Granian
from granian.constants import Interfaces
from granian.log import LogLevels
from pydantic import BaseModel, Field
from pymongo import AsyncMongoClient, MongoClient, ReturnDocument
from pymongo.monitoring import (
    CommandFailedEvent,
    CommandListener,
    CommandStartedEvent,
    CommandSucceededEvent,
)
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from client_query_cache import SharedCacheConnection, SharedCacheServer
from client_query_cache._types import NonNegativeInt, PositiveInt
from client_query_cache.asynchronous import SharedCachedCollection, SharedCacheManager

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator
    from http.client import HTTPResponse

    from pymongo.asynchronous.collection import AsyncCollection

DATABASE_NAME = "client_query_cache_example_fastapi_shared"
MONGODB_URI = os.getenv(
    "MONGODB_URI", "mongodb://localhost:27017/?directConnection=true"
)
NonEmptyStr = Annotated[str, Field(min_length=1)]
STARTED = re.compile(r"worker (\d+): shared manager started")
CLOSED = re.compile(r"worker (\d+): shared manager closed before client")


class Product(TypedDict):
    _id: NonEmptyStr
    description: NonEmptyStr
    tenant_id: NonEmptyStr


class DescriptionUpdate(BaseModel):
    description: Annotated[str, Field(min_length=1, max_length=200)]


class WorkerIdentity(BaseModel):
    pid: PositiveInt


class Observation(WorkerIdentity):
    product: Product
    hits: NonNegativeInt
    misses: NonNegativeInt
    bypasses: NonNegativeInt
    database_reads: NonNegativeInt


class DatabaseReads(CommandListener):
    """Count actual find commands without retaining queries or credentials."""

    def __init__(self) -> None:
        self.count: NonNegativeInt = 0

    def started(self, event: CommandStartedEvent) -> None:
        if event.command_name == "find":
            self.count += 1

    def succeeded(self, event: CommandSucceededEvent) -> None:
        pass

    def failed(self, event: CommandFailedEvent) -> None:
        pass


@dataclass
class Resources:
    raw: AsyncCollection[Product]
    cached: SharedCachedCollection[Product]
    manager: SharedCacheManager[Product]
    reads: DatabaseReads


def resources(request: Request) -> Resources:
    owned: Resources = request.app.state.resources
    return owned


# --8<-- [start:application]
def create_app(connection: SharedCacheConnection) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        reads = DatabaseReads()
        async with (
            AsyncMongoClient[Product](
                MONGODB_URI,
                event_listeners=[reads],
                serverSelectionTimeoutMS=5000,
                timeoutMS=5000,
            ) as client,
            SharedCacheManager(client, connection) as manager,
        ):
            raw = client[DATABASE_NAME].get_collection(
                "products",
                read_concern=ReadConcern("majority"),
                write_concern=WriteConcern(w="majority"),
            )
            app.state.resources = Resources(
                raw, manager.get_cached_collection(raw), manager, reads
            )
            print(f"worker {os.getpid()}: shared manager started", flush=True)
            yield
        print(f"worker {os.getpid()}: shared manager closed before client", flush=True)

    app = FastAPI(lifespan=lifespan)
    app.get("/health")(health)
    app.get("/products/{product_id}")(read_product)
    app.patch("/products/{product_id}")(update_product)
    return app


def health() -> WorkerIdentity:
    return WorkerIdentity(pid=os.getpid())


async def read_product(
    product_id: NonEmptyStr,
    request: Request,
    worker_pid: PositiveInt | None = None,
) -> Observation:
    # Targeting is only for the demonstration: a rejected worker performs no read.
    if worker_pid is not None and worker_pid != os.getpid():
        raise HTTPException(status_code=409, detail="Try another worker")
    owned = resources(request)
    product = await owned.cached.find_one({"_id": product_id, "tenant_id": "demo"})
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    counts = owned.manager.snapshot()
    return Observation(
        pid=os.getpid(),
        product=product,
        hits=counts.hits,
        misses=counts.misses,
        bypasses=counts.bypasses,
        database_reads=owned.reads.count,
    )


async def update_product(
    product_id: NonEmptyStr,
    update: DescriptionUpdate,
    request: Request,
) -> Product:
    product = await resources(request).raw.find_one_and_update(
        {"_id": product_id, "tenant_id": "demo"},
        {"$set": {"description": update.description}},
        return_document=ReturnDocument.AFTER,
    )
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


def serve(workers: PositiveInt, port: PositiveInt) -> None:
    with SharedCacheServer(
        MONGODB_URI,
        (DATABASE_NAME,),
        client_options={"serverSelectionTimeoutMS": 5000, "timeoutMS": 5000},
    ) as cache_server:
        Granian(
            "shared-products",
            interface=Interfaces.ASGI,
            workers=workers,
            address="127.0.0.1",
            port=port,
            log_level=LogLevels.error,
            workers_kill_timeout=10,
        ).serve(
            target_loader=partial(create_app, cache_server.connection),
            wrap_loader=False,
        )
    print("parent: shared cache server closed after workers", flush=True)


# --8<-- [end:application]


def require(*, condition: bool, message: NonEmptyStr) -> None:
    if not condition:
        raise AssertionError(message)


def response_body(port: PositiveInt, path: NonEmptyStr) -> bytes:
    # Every request opens a connection so it can reach a different worker.
    response: HTTPResponse
    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}{path}", timeout=2
    ) as response:
        return response.read()


def read_worker(port: PositiveInt, pid: PositiveInt) -> Observation:
    deadline = monotonic() + 15
    while monotonic() < deadline:
        try:
            return Observation.model_validate_json(
                response_body(port, f"/products/book?worker_pid={pid}")
            )
        except urllib.error.HTTPError as error:
            if error.code != 409:
                raise
        sleep(0.01)
    message = f"No request reached worker {pid}"
    raise AssertionError(message)


def wait_for_hit(
    port: PositiveInt, pid: PositiveInt, description: NonEmptyStr
) -> Observation:
    previous = read_worker(port, pid)
    deadline = monotonic() + 15
    while monotonic() < deadline:
        current = read_worker(port, pid)
        if (
            current.product["description"] == description
            and current.hits > previous.hits
        ):
            return current
        previous = current
        sleep(0.02)
    message = f"Worker {pid} did not hit the expected document"
    raise AssertionError(message)


def worker_pids(port: PositiveInt) -> tuple[PositiveInt, PositiveInt]:
    pids: set[PositiveInt] = set()
    deadline = monotonic() + 30
    while monotonic() < deadline:
        try:
            pids.add(
                WorkerIdentity.model_validate_json(response_body(port, "/health")).pid
            )
        except urllib.error.URLError as error:
            if not isinstance(error.reason, ConnectionRefusedError):
                raise
        if len(pids) == 2:
            first, second = sorted(pids)
            return first, second
        sleep(0.02)
    raise AssertionError("Two HTTP workers did not become ready")


@contextmanager
def running_server(port: PositiveInt) -> Generator[None]:
    process = subprocess.Popen(  # noqa: S603 - Launch this repository example without a shell.
        (sys.executable, __file__, "--serve", "--workers", "2", "--port", str(port)),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    try:
        yield
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
        try:
            output, _ = process.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            output, _ = process.communicate()
            print(output, end="")
            raise
        print(output, end="")
        require(
            condition=process.returncode == 0,
            message="Server failed or shutdown was not graceful",
        )
        started = set(STARTED.findall(output))
        require(
            condition=len(started) == 2 and set(CLOSED.findall(output)) == started,
            message="Every worker must close its manager before its client",
        )
        require(
            condition="parent: shared cache server closed after workers" in output,
            message="Parent did not close the shared server",
        )


def verify(port: PositiveInt) -> None:
    first_pid, second_pid = worker_pids(port)
    warm = wait_for_hit(port, first_pid, "original description")
    shared = read_worker(port, second_pid)
    require(
        condition=shared.hits == 1 and shared.database_reads == 0,
        message="The second worker's first read must hit without a MongoDB find",
    )
    print(
        f"shared hit: worker {first_pid} warmed; "
        f"worker {second_pid} read with zero MongoDB finds"
    )

    update = urllib.request.Request(
        f"http://127.0.0.1:{port}/products/book",
        method="PATCH",
        data=json.dumps({"description": "updated description"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(update, timeout=5) as response:  # noqa: S310 - The request uses a fixed localhost HTTP URL.
        product = json.load(response)
    require(
        condition=product["description"] == "updated description",
        message="PATCH must return the updated document directly",
    )
    refreshed = tuple(
        wait_for_hit(port, pid, "updated description")
        for pid in (first_pid, second_pid)
    )
    require(
        condition=sum(item.database_reads for item in refreshed) > warm.database_reads,
        message="Invalidation must force a MongoDB refetch",
    )
    print("invalidation: both workers hit the updated document after a raw PATCH")


def self_check() -> None:
    with MongoClient[Product](MONGODB_URI, timeoutMS=5000) as client:
        client.drop_database(DATABASE_NAME)
        try:
            client[DATABASE_NAME].get_collection(
                "products", write_concern=WriteConcern(w="majority")
            ).insert_one(
                {
                    "_id": "book",
                    "description": "original description",
                    "tenant_id": "demo",
                }
            )
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port: PositiveInt = listener.getsockname()[1]
            with running_server(port):
                verify(port)
        finally:
            client.drop_database(DATABASE_NAME)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="FastAPI shared caching with real Granian workers"
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Serve existing data; default runs a disposable self-check",
    )
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--port", type=int, default=8000)
    arguments = parser.parse_args()
    if arguments.workers < 2 or not 1 <= arguments.port <= 65535:
        parser.error("Use at least two workers and a port from 1 through 65535")
    if arguments.serve:
        multiprocessing.set_start_method("spawn")
        serve(arguments.workers, arguments.port)
    else:
        self_check()


if __name__ == "__main__":
    main()
