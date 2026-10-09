from __future__ import annotations

import multiprocessing
import secrets
import shutil
import tempfile
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
from pymongo import MongoClient

from benchmarks.stream_cost.multiprocess_run import reclaim_workers
from benchmarks.stream_cost.shared_cache.coordinator import OwnerConfig, TransportLimits
from benchmarks.stream_cost.shared_cache.owner import owner_main
from benchmarks.stream_cost.shared_cache.window import attachment_for

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from multiprocessing.connection import Connection
    from multiprocessing.process import BaseProcess

    from benchmarks.stream_cost.shared_cache.attachment import AttachmentConfig
    from tests.conftest import DatabaseName, MongoDbUri

type Payload = dict[str, Any]

COLLECTION = "catalogue"
DOCUMENTS = 32
# Idle polls complete every 100 ms, well inside the 600 ms progress expiry.
AWAIT_MS = 100
LIMITS = TransportLimits(
    rpc_deadline_seconds=0.5,
    progress_expiry_seconds=0.6,
    queued_bytes_per_connection=262_144,
    requests_per_connection=256,
    connections=16,
    captures=64,
    capture_seconds=30.0,
    frame_overhead_bytes=65_536,
)


@dataclass(slots=True)
class Owner:
    config: OwnerConfig
    control: Connection
    process: BaseProcess
    pid: int

    def request(self, operation: str, **fields: object) -> Payload:
        self.control.send({"op": operation, **fields})
        assert self.control.poll(10)
        return cast("Payload", self.control.recv())

    def observation(self) -> Payload:
        return cast("Payload", self.request("sample")["observation"])

    def counters(self) -> Payload:
        return cast("Payload", self.observation()["counters"])

    def attachment(self, **changes: object) -> AttachmentConfig:
        return replace(attachment_for(self.config), **changes)  # type: ignore[arg-type]

    def stop(self) -> None:
        if self.process.is_alive():
            self.control.send("close")
            assert self.control.poll(10)
            assert self.control.recv() == {"kind": "closed"}
        self.control.close()
        reclaim_workers((self.process,), time.monotonic() + 10, graceful=True)


def wait_for(predicate: Callable[[], bool], timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition was not reached in time"
        time.sleep(0.02)


@pytest.fixture
def seeded_database(
    mongodb_uri: MongoDbUri, cached_database_name: DatabaseName
) -> Iterator[str]:
    with MongoClient[dict[str, Any]](mongodb_uri) as client:
        client[cached_database_name][COLLECTION].insert_many(
            {"_id": index, "payload": f"value-{index}", "revision": 0}
            for index in range(DOCUMENTS)
        )
        yield cached_database_name
        client.drop_database(cached_database_name)


@pytest.fixture
def socket_directory() -> Iterator[Path]:
    directory = Path(tempfile.mkdtemp(prefix="sc-"))
    yield directory
    shutil.rmtree(directory)


@pytest.fixture
def start_owner(
    mongodb_uri: MongoDbUri, seeded_database: str, socket_directory: Path
) -> Iterator[Callable[..., Owner]]:
    owners: list[Owner] = []
    capability = secrets.token_bytes(32)

    def start(**limits: object) -> Owner:
        config = OwnerConfig(
            socket_path=str(socket_directory / "owner.sock"),
            capability=capability,
            mongodb_uri=mongodb_uri,
            client_options={
                "directConnection": True,
                "serverSelectionTimeoutMS": 10_000,
            },
            databases=(seeded_database,),
            budget_bytes=8 * 1024 * 1024,
            max_entry_bytes=1024 * 1024,
            max_await_time_ms=AWAIT_MS,
            limits=replace(LIMITS, **limits),  # type: ignore[arg-type]
            lag_capture=(1, 1, 0),
        )
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        process = context.Process(target=owner_main, args=(config, child))
        process.start()
        child.close()
        assert parent.poll(30)
        ready = cast("Payload", parent.recv())
        if ready["kind"] == "failure":
            process.join(10)
            parent.close()
            raise RuntimeError(ready["error"])
        owner = Owner(config, parent, process, ready["pid"])
        owners.append(owner)
        return owner

    yield start
    for owner in owners:
        owner.stop()
