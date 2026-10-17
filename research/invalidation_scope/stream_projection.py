"""Measure stream projection costs independently of proposed cache guards."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import threading
import time
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from itertools import product
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse

import bson
import pymongo
from pymongo.errors import PyMongoError

from benchmarks.mongodb_image import MONGODB_IMAGE
from benchmarks.stream_cost.client import (
    BenchmarkClientTopologyConfig,
    WireCompressor,
    build_dedicated_client,
)
from benchmarks.stream_cost.generators import generate_seeded_documents
from benchmarks.stream_cost.measurement import measure_controlled
from benchmarks.stream_cost.proxy import DirectPathByteProxy, DirectPathProxyConfig
from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits
from benchmarks.stream_cost.workload import DATA_SIZE_PROFILES
from client_query_cache._core.stream_events import (
    build_change_stream_pipeline,
)
from client_query_cache._types import (
    BsonDict,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
)

if TYPE_CHECKING:
    from pymongo.synchronous.change_stream import ChangeStream
    from pymongo.synchronous.database import Database

Mode = Literal["none", "routing", "scalar", "names", "full_insert"]
MODES: tuple[Mode, ...] = ("none", "routing", "scalar", "names", "full_insert")
MAX_STRING_BYTES = 64
MAX_NAMES = 32
SEED = 257
DOCUMENT_COUNT = 100
AWAIT_MS = 1_000
DEADLINE_SECONDS = 15.0
TOPOLOGY = BenchmarkClientTopologyConfig(
    tls_enabled=False,
    compressor=WireCompressor.NONE,
    discovery_enabled=False,
    shared_connections=False,
)


def pipeline(
    mode: Mode, *, scalar_field: Literal["index", "author_id"] = "index"
) -> list[BsonDict]:
    stages = [dict(stage) for stage in build_change_stream_pipeline()]
    projection = stages[-1]["$project"]
    scalar_path = f"$fullDocument.{scalar_field}"
    if mode == "scalar":
        bounded = {
            "$switch": {
                "branches": [
                    {
                        "case": {"$eq": [{"$type": scalar_path}, "string"]},
                        "then": {
                            "$lte": [
                                {"$strLenBytes": scalar_path},
                                MAX_STRING_BYTES,
                            ]
                        },
                    }
                ],
                "default": {"$in": [{"$type": scalar_path}, ["int", "long", "bool"]]},
            }
        }
        projection["partition"] = {
            "$cond": [
                {"$eq": ["$operationType", "insert"]},
                {
                    "$cond": [
                        bounded,
                        {"known": True, "value": scalar_path},
                        {"known": False},
                    ]
                },
                "$$REMOVE",
            ]
        }
    elif mode == "names":
        names = {
            "$concatArrays": [
                {
                    "$map": {
                        "input": {
                            "$objectToArray": {
                                "$ifNull": ["$updateDescription.updatedFields", {}]
                            }
                        },
                        "as": "field",
                        "in": "$$field.k",
                    }
                },
                {"$ifNull": ["$updateDescription.removedFields", []]},
                {
                    "$map": {
                        "input": {
                            "$ifNull": ["$updateDescription.truncatedArrays", []]
                        },
                        "as": "field",
                        "in": "$$field.field",
                    }
                },
            ]
        }
        projection["changes"] = {
            "$cond": [
                {"$eq": ["$operationType", "update"]},
                {
                    "$let": {
                        "vars": {"names": names},
                        "in": {
                            "$cond": [
                                {
                                    "$and": [
                                        {"$lte": [{"$size": "$$names"}, MAX_NAMES]},
                                        {
                                            "$allElementsTrue": {
                                                "$map": {
                                                    "input": "$$names",
                                                    "as": "name",
                                                    "in": {
                                                        "$lte": [
                                                            {"$strLenBytes": "$$name"},
                                                            MAX_STRING_BYTES,
                                                        ]
                                                    },
                                                }
                                            }
                                        },
                                    ]
                                },
                                {"known": True, "names": "$$names"},
                                {"known": False},
                            ]
                        },
                    }
                },
                "$$REMOVE",
            ]
        }
    elif mode == "full_insert":
        projection["fullDocument"] = {
            "$cond": [
                {"$eq": ["$operationType", "insert"]},
                "$fullDocument",
                "$$REMOVE",
            ]
        }
    return stages


def open_stream(database: Database[BsonDict], mode: Mode) -> ChangeStream[BsonDict]:
    return database.watch(
        pipeline(mode), show_expanded_events=True, max_await_time_ms=AWAIT_MS
    )


def next_write(stream: ChangeStream[BsonDict]) -> BsonDict:
    deadline = time.monotonic() + DEADLINE_SECONDS
    while time.monotonic() < deadline:
        event = stream.try_next()
        if event is not None and event["operationType"] in {
            "insert",
            "update",
            "replace",
            "delete",
        }:
            return event
    raise TimeoutError("projection verification did not receive its write")


def verify_projections(database: Database[BsonDict]) -> None:
    collection = database["verify"]
    collection.insert_one({"_id": -1})
    values: tuple[object, ...] = (
        0,
        2**40,
        False,
        "a" * 64,
        "é" * 32,
        "é" * 33,
        None,
        [],
        {},
        1.5,
    )
    with open_stream(database, "scalar") as stream:
        for identity, value in enumerate(values):
            collection.insert_one({"_id": identity, "index": value})
            partition = next_write(stream)["partition"]
            assert partition == (
                {"known": True, "value": value} if identity < 5 else {"known": False}
            )
        collection.insert_one({"_id": len(values)})
        assert next_write(stream)["partition"] == {"known": False}
    with open_stream(database, "names") as stream:
        for fields in (
            {"large": "x" * 20_000},
            {"é" * 33: 1},
            {f"field_{index}": 1 for index in range(MAX_NAMES)},
            {f"other_{index}": 1 for index in range(MAX_NAMES + 1)},
        ):
            collection.update_one({"_id": -1}, {"$set": fields})
            changes = next_write(stream)["changes"]
            assert isinstance(changes, dict)
            known = len(fields) <= MAX_NAMES and all(
                len(name.encode()) <= MAX_STRING_BYTES for name in fields
            )
            assert changes["known"] == known
            if known:
                assert set(changes["names"]) == set(fields)
        collection.update_one({"_id": -1}, {"$unset": {"large": ""}})
        assert next_write(stream)["changes"] == {"known": True, "names": ["large"]}
        collection.update_one({"_id": -1}, {"$set": {"array": [1, 2, 3, 4]}})
        next_write(stream)
        collection.update_one(
            {"_id": -1}, [{"$set": {"array": {"$slice": ["$array", 2]}}}]
        )
        assert next_write(stream)["changes"] == {"known": True, "names": ["array"]}
        collection.replace_one({"_id": -1}, {"_id": -1, "replacement": True})
        assert "changes" not in next_write(stream)
    with open_stream(database, "full_insert") as stream:
        document: BsonDict = {"_id": "full", "padding": "x" * 20_000}
        collection.insert_one(document)
        assert next_write(stream)["fullDocument"] == document
    database.drop_collection("verify")


@dataclass(slots=True)
class Consumer:
    stream: ChangeStream[BsonDict]
    stopped: threading.Event
    condition: threading.Condition
    writes: NonNegativeInt = 0
    logical_bytes: NonNegativeInt = 0
    failure: PyMongoError | None = None

    def consume(self) -> None:
        while not self.stopped.is_set():
            try:
                event = self.stream.try_next()
            except PyMongoError as error:
                with self.condition:
                    self.failure = error
                    self.condition.notify_all()
                return
            if event is not None:
                with self.condition:
                    self.logical_bytes += len(bson.encode(event))
                    if event["operationType"] in {"insert", "update"}:
                        self.writes += 1
                    self.condition.notify_all()

    def drain(self, expected: NonNegativeInt) -> None:
        with self.condition:
            complete = self.condition.wait_for(
                lambda: self.writes >= expected or self.failure is not None,
                timeout=DEADLINE_SECONDS,
            )
            if self.failure is not None:
                raise self.failure
            if not complete or self.writes != expected:
                message = f"expected {expected} events, received {self.writes}"
                raise RuntimeError(message)


def run_cell(
    replica_set: IsolatedReplicaSet,
    database: Database[BsonDict],
    stream_database: Database[BsonDict],
    proxy: DirectPathByteProxy,
    *,
    mode: Mode,
    documents: list[BsonDict],
    reads_per_ten_writes: NonNegativeInt,
    rate: NonNegativeInt,
    seconds: PositiveFloat,
    uncached: bool,
) -> BsonDict:
    for name in ("cached", "uncached"):
        database[name].delete_many({})
        database[name].insert_many(documents)
    target = database["uncached" if uncached else "cached"]
    with ExitStack() as stack:
        consumer = None
        if mode != "none":
            stream = stack.enter_context(open_stream(stream_database, mode))
            consumer = Consumer(stream, threading.Event(), threading.Condition())
            worker = threading.Thread(target=consumer.consume, daemon=True)
            worker.start()

            def stop_consumer() -> None:
                consumer.stopped.set()
                worker.join(timeout=DEADLINE_SECONDS)
                if worker.is_alive():
                    raise TimeoutError("stream consumer did not stop")

            stack.callback(stop_consumer)

        write_count = round(rate * seconds)
        reads = write_count * reads_per_ten_writes // 10
        padding = documents[0]["padding"]
        assert isinstance(padding, str)
        padding_length = len(padding)

        def exercise() -> None:
            started = time.monotonic()
            for index in range(write_count):
                remaining = started + index / rate - time.monotonic()
                if remaining > 0:
                    time.sleep(remaining)
                if index % 2 == 0:
                    document = dict(documents[index % DOCUMENT_COUNT])
                    document["_id"] = f"insert-{index}"
                    target.insert_one(document)
                else:
                    update = (
                        {"$inc": {"index": 1}}
                        if index % 4 == 1
                        else {
                            "$set": {
                                "padding": chr(ord("a") + index // DOCUMENT_COUNT % 26)
                                * padding_length
                            }
                        }
                    )
                    written = target.update_one(
                        {"_id": documents[index % DOCUMENT_COUNT]["_id"]}, update
                    )
                    assert written.modified_count == 1
                for read_index in range(
                    index * reads // write_count, (index + 1) * reads // write_count
                ):
                    fetched = database["cached"].find_one(
                        {"_id": documents[read_index % DOCUMENT_COUNT]["_id"]}
                    )
                    assert fetched is not None
            remaining = started + seconds - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
            if consumer is not None:
                consumer.drain(write_count)

        try:
            _, measurement = measure_controlled(
                exercise, replica_set=replica_set, proxy=proxy
            )
            return {
                "mode": mode,
                "uncached": uncached,
                "requested_writes_per_second": rate,
                "reads": reads,
                "writes": write_count,
                "observed_events": 0 if consumer is None else consumer.writes,
                "logical_bytes": 0 if consumer is None else consumer.logical_bytes,
                **asdict(measurement),
            }
        finally:
            if consumer is not None:
                consumer.stopped.set()


def acquire(
    replica_set: IsolatedReplicaSet,
    database: Database[BsonDict],
    stream_database: Database[BsonDict],
    proxy: DirectPathByteProxy,
    *,
    reps: PositiveInt,
    seconds: PositiveFloat,
) -> list[BsonDict]:
    cells: list[BsonDict] = []
    workloads = (
        ("idle", 0, 0),
        *(
            (kind, ratio, rate)
            for (kind, ratio), rate in product(
                (("read_heavy", 100), ("balanced", 10), ("write_dominant", 1)),
                (10, 100),
            )
        ),
    )
    for rep, profile in product(range(reps), DATA_SIZE_PROFILES):
        modes = MODES if rep % 2 == 0 else tuple(reversed(MODES))
        documents = generate_seeded_documents(
            seed=SEED, count=DOCUMENT_COUNT, profile=profile
        )
        for (kind, ratio, rate), uncached, mode in product(
            workloads, (False, True), modes
        ):
            cell = run_cell(
                replica_set,
                database,
                stream_database,
                proxy,
                mode=mode,
                documents=documents,
                reads_per_ten_writes=ratio,
                rate=rate,
                seconds=seconds,
                uncached=uncached,
            )
            cells.append(
                {
                    "rep": rep,
                    "size": profile.target_bytes,
                    "kind": kind,
                    **cell,
                }
            )
    return cells


def run(reps: PositiveInt, seconds: PositiveFloat, *, verify_only: bool) -> BsonDict:
    with (
        IsolatedReplicaSet(ResourceLimits(cpus=2.0, memory="2g")) as replica_set,
        replica_set.build_client(TOPOLOGY) as client,
    ):
        address = urlparse(replica_set.uri)
        assert address.hostname is not None
        assert address.port is not None
        with (
            DirectPathByteProxy(
                DirectPathProxyConfig(TOPOLOGY, address.hostname, address.port)
            ) as proxy,
            build_dedicated_client(
                f"mongodb://127.0.0.1:{proxy.local_port}", TOPOLOGY
            ) as stream_client,
        ):
            stream_client.admin.command("ping")
            database = client["projection_cost"]
            stream_database = stream_client[database.name]
            verify_projections(stream_database)
            if verify_only:
                documents = generate_seeded_documents(
                    seed=SEED, count=DOCUMENT_COUNT, profile=DATA_SIZE_PROFILES[0]
                )
                for mode in MODES:
                    run_cell(
                        replica_set,
                        database,
                        stream_database,
                        proxy,
                        mode=mode,
                        documents=documents,
                        reads_per_ten_writes=0,
                        rate=100,
                        seconds=2.0,
                        uncached=True,
                    )
            cells = (
                []
                if verify_only
                else acquire(
                    replica_set,
                    database,
                    stream_database,
                    proxy,
                    reps=reps,
                    seconds=seconds,
                )
            )
            return {
                "python": platform.python_version(),
                "harness_sha256": hashlib.sha256(
                    Path(__file__).read_bytes()
                ).hexdigest(),
                "pymongo": pymongo.version,
                "mongodb": client.server_info()["version"],
                "image": MONGODB_IMAGE,
                "cpus": 2,
                "memory": "2g",
                "reps": reps,
                "seconds": seconds,
                "cells": cells,
            }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--seconds", type=float, default=2.0)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.reps < 1 or not 0.1 <= args.seconds <= 60:
        parser.error("--reps must be positive and --seconds must be in [0.1, 60]")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as output:
        measurements = run(args.reps, args.seconds, verify_only=args.verify_only)
        json.dump(measurements, output, indent=2)
        output.write("\n")


if __name__ == "__main__":
    main()
