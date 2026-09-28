from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import json
import multiprocessing
import platform
import shutil
import subprocess
import time
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, cast
from urllib.parse import urlsplit

import pymongo
from pymongo import AsyncMongoClient, MongoClient
from pymongo.errors import PyMongoError

from benchmarks.stream_cost.await_commands import AwaitCommandListener
from benchmarks.stream_cost.await_configuration import load_await_configuration
from benchmarks.stream_cost.await_decision import evaluate_await_decision
from benchmarks.stream_cost.await_model import (
    AwaitConfiguration,
    AwaitWindow,
    AwaitWorkload,
    ExecutionModel,
    planned_windows,
)
from benchmarks.stream_cost.await_report import (
    configuration_hash,
    validate_await_report,
)
from benchmarks.stream_cost.client import BenchmarkClientTopologyConfig, WireCompressor
from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.proxy import DirectPathByteProxy, DirectPathProxyConfig
from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits
from client_query_cache.asynchronous.manager import CacheManager as AsyncCacheManager
from client_query_cache.synchronous.manager import CacheManager

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from multiprocessing.connection import Connection

_CONFIG_PATH = Path("reports/stream-cost/await-v1/config.v1.json")
_TOPOLOGY = BenchmarkClientTopologyConfig(
    tls_enabled=False,
    compressor=WireCompressor.NONE,
    discovery_enabled=False,
    shared_connections=False,
)


async def _invoke[**P, T](
    function: Callable[P, T | Awaitable[T]], *args: P.args, **kwargs: P.kwargs
) -> T:
    value = function(*args, **kwargs)
    if inspect.isawaitable(value):
        return await value
    return value


async def _wait_for(
    predicate: Callable[[], bool], seconds: float, listener: AwaitCommandListener
) -> None:
    async with asyncio.timeout(seconds):
        while True:
            version = listener.version
            if predicate():
                return
            await asyncio.to_thread(listener.wait_for_change, version, seconds)


async def _wait_for_command_count(
    listener: AwaitCommandListener, count: int, seconds: float
) -> None:
    await _wait_for(lambda: len(listener.snapshot()) >= count, seconds, listener)


type _Client = MongoClient[dict[str, object]] | AsyncMongoClient[dict[str, object]]
type _Manager = CacheManager[dict[str, object]] | AsyncCacheManager[dict[str, object]]


def _build_manager(
    uri: str, model: ExecutionModel, candidate: int, listener: AwaitCommandListener
) -> tuple[_Client, _Manager]:
    if model == "sync":
        client = MongoClient[dict[str, object]](
            uri,
            directConnection=True,
            serverSelectionTimeoutMS=10000,
            event_listeners=[listener],
        )
        return client, CacheManager(client, max_await_time_ms=candidate)
    async_client = AsyncMongoClient[dict[str, object]](
        uri,
        directConnection=True,
        serverSelectionTimeoutMS=10000,
        event_listeners=[listener],
    )
    return async_client, AsyncCacheManager(async_client, max_await_time_ms=candidate)


@dataclass(frozen=True, slots=True)
class WindowStart:
    wall_seconds: float  # Monotonic time can be zero.
    process_cpu_seconds: float  # CPU counter can be zero.
    server_cpu_seconds: float  # CPU counter can be zero.
    bytes_sent: int  # Byte counter can be zero.
    bytes_received: int  # Byte counter can be zero.
    command_offset: int  # Zero-based offset into observed command metadata.


def _capture_start(
    replica: IsolatedReplicaSet,
    proxy: DirectPathByteProxy,
    listener: AwaitCommandListener,
    *,
    before_command: bool,
) -> WindowStart:
    server = replica.container_cpu_usage_seconds()
    command_count = len(listener.snapshot())
    offset = command_count if before_command else max(0, command_count - 1)
    sent, received = proxy.bytes_sent, proxy.bytes_received
    process = time.process_time()
    return WindowStart(time.monotonic(), process, server, sent, received, offset)


async def _idle_start(
    replica: IsolatedReplicaSet,
    proxy: DirectPathByteProxy,
    listener: AwaitCommandListener,
    candidate: int,
) -> WindowStart:
    captures: list[WindowStart] = []  # Empty until the next command boundary.
    failures: list[BenchmarkSetupError] = []  # Empty unless resource observation fails.

    def capture() -> None:
        try:
            captures.append(
                _capture_start(replica, proxy, listener, before_command=True)
            )
        except BenchmarkSetupError as error:
            failures.append(error)

    listener.at_next_start(capture)
    await _wait_for(
        lambda: bool(captures) or bool(failures), candidate / 1000 + 10, listener
    )
    if failures:
        raise failures[0]
    return captures[0]


def _issue_write(
    client: MongoClient[dict[str, object]], database: str, value: int
) -> float:
    issued = time.monotonic()
    client[database]["measured"].update_one({"_id": 0}, {"$set": {"value": value}})
    return issued


async def run_window(
    replica: IsolatedReplicaSet,
    configuration: AwaitConfiguration,
    *,
    block: int,
    candidate: int,
    model: ExecutionModel,
    workload: AwaitWorkload,
) -> AwaitWindow:
    address = urlsplit(replica.uri)
    assert address.hostname is not None
    assert address.port is not None
    listener = AwaitCommandListener()
    database_name = f"await_{block}_{candidate}_{model}_{workload}"
    with ExitStack() as resources:
        writer = resources.enter_context(
            MongoClient[dict[str, object]](replica.uri, serverSelectionTimeoutMS=10000)
        )
        writer.drop_database(database_name)
        writer[database_name]["measured"].insert_one(
            {"_id": 0, "value": 0, "padding": "x" * 256}
        )
        proxy = resources.enter_context(
            DirectPathByteProxy(
                DirectPathProxyConfig(_TOPOLOGY, address.hostname, address.port)
            )
        )
        client, manager = _build_manager(
            f"mongodb://127.0.0.1:{proxy.local_port}/?directConnection=true",
            model,
            candidate,
            listener,
        )
        try:
            collection = manager[database_name]["measured"]
            await _invoke(collection.find_one, {"_id": 0})
            await asyncio.sleep(configuration["warmup_seconds"])
            before = manager.cache_core.stream_cost_snapshot(database_name)
            boundary = (
                await _idle_start(replica, proxy, listener, candidate)
                if workload == "idle"
                else _capture_start(replica, proxy, listener, before_command=False)
            )
            first_index = boundary.command_offset
            start = boundary.wall_seconds
            issue_offsets: list[float] = []
            if workload == "idle":
                await asyncio.sleep(configuration["idle_minimum_seconds"])
                await _wait_for(
                    lambda: (
                        sum(
                            command.completed_seconds is not None
                            for command in listener.snapshot()[first_index:]
                        )
                        >= configuration["idle_minimum_completed_commands"]
                    ),
                    candidate / 1000 + 10,
                    listener,
                )
            else:
                for index, offset in enumerate(
                    configuration["write_offsets_seconds"][workload], start=1
                ):
                    await asyncio.sleep(max(0, start + offset - time.monotonic()))
                    actual = (
                        await asyncio.to_thread(
                            _issue_write, writer, database_name, index
                        )
                        - start
                    )
                    if (
                        actual - offset
                        > configuration["write_schedule_tolerance_seconds"][workload]
                    ):
                        raise BenchmarkSetupError(
                            "write schedule exceeded its registered tolerance"
                        )
                    issue_offsets.append(actual)
                await _wait_for(
                    lambda: (
                        manager.cache_core.stream_cost_snapshot(
                            database_name
                        ).invalidations
                        - before.invalidations
                        == len(issue_offsets)
                    ),
                    configuration["event_settle_timeout_seconds"],
                    listener,
                )
                await asyncio.sleep(
                    max(
                        0,
                        start
                        + configuration["active_window_seconds"]
                        - time.monotonic(),
                    )
                )
            end = time.monotonic()
            elapsed = end - start
            cpu = time.process_time() - boundary.process_cpu_seconds
            sent, received = (
                proxy.bytes_sent - boundary.bytes_sent,
                proxy.bytes_received - boundary.bytes_received,
            )
            server = replica.container_cpu_usage_seconds() - boundary.server_cpu_seconds
            after = manager.cache_core.stream_cost_snapshot(database_name)
            commands = tuple(
                command
                for command in listener.snapshot()[first_index:]
                if command.started_seconds <= end
                and (
                    command.completed_seconds is None
                    or command.completed_seconds >= start
                )
            )
            lag = tuple(
                reading.monotonic_seconds - start - issued
                for reading, issued in zip(
                    after.invalidation_apply_readings[
                        len(before.invalidation_apply_readings) :
                    ],
                    issue_offsets,
                    strict=True,
                )
            )
            healthy = manager.cache_core.is_database_available(database_name)
            if not healthy or any(command.failed for command in commands):
                raise BenchmarkSetupError(
                    "stream health or command failure during measured window"
                )
            return AwaitWindow(
                block,
                candidate,
                model,
                workload,
                elapsed,
                server,
                cpu,
                sent,
                received,
                sum(command.started_seconds >= start for command in commands),
                sum(
                    command.completed_seconds is not None
                    and command.completed_seconds <= end
                    for command in commands
                ),
                tuple(command.max_time_ms for command in commands),
                sum(command.failed for command in commands),
                after.stream_polls - before.stream_polls,
                tuple(issue_offsets),
                lag,
                (),
                after.invalidations - before.invalidations,
                healthy,
                None,
                getmore_inflight_at_start=sum(
                    command.started_seconds < start for command in commands
                ),
            )
        finally:
            await _invoke(manager.close)
            await _invoke(client.close)
            writer.drop_database(database_name)


async def run_shutdown(
    uri: str,
    configuration: AwaitConfiguration,
    *,
    block: int,
    candidate: int,
    model: ExecutionModel,
) -> AwaitWindow:
    durations: list[float] = []
    actual_offsets: list[float] = []
    requested: list[int | None] = []
    started_count = completed_count = failed_count = inflight_count = 0
    for trial, offset in enumerate(configuration["shutdown_trial_offsets_seconds"]):
        listener = AwaitCommandListener()
        client, manager = _build_manager(uri, model, candidate, listener)
        try:
            await _invoke(
                manager[f"await_shutdown_{block}_{candidate}_{model}_{trial}"][
                    "measured"
                ].find_one,
                {"_id": 0},
            )
            await _wait_for_command_count(listener, 1, 10)
            await asyncio.sleep(
                max(
                    0,
                    listener.snapshot()[0].started_seconds + offset - time.monotonic(),
                )
            )
            started = time.monotonic()
            first_command = listener.snapshot()[0]
            if (
                first_command.completed_seconds is not None
                and first_command.completed_seconds <= started
            ):
                raise BenchmarkSetupError(
                    "shutdown trial did not start during an in-flight getMore"
                )
            phase = started - first_command.started_seconds
            if (
                not 0
                <= phase - offset
                <= configuration["shutdown_schedule_tolerance_seconds"]
            ):
                raise BenchmarkSetupError(
                    "shutdown schedule exceeded its registered tolerance"
                )
            actual_offsets.append(phase)
            await _invoke(manager.close)
            ended = time.monotonic()
            durations.append(ended - started)
            commands = tuple(
                command
                for command in listener.snapshot()
                if command.started_seconds <= ended
                and (
                    command.completed_seconds is None
                    or command.completed_seconds >= started
                )
            )
            inflight = sum(command.started_seconds < started for command in commands)
            inflight_count += inflight
            started_count += sum(
                command.started_seconds >= started for command in commands
            )
            completed_count += sum(
                command.completed_seconds is not None
                and command.completed_seconds <= ended
                for command in commands
            )
            failed_count += sum(command.failed for command in commands)
            requested.extend(command.max_time_ms for command in commands)
        finally:
            await _invoke(manager.close)
            await _invoke(client.close)
    return AwaitWindow(
        block,
        candidate,
        model,
        "shutdown",
        sum(durations),
        None,
        None,
        None,
        None,
        started_count,
        completed_count,
        tuple(requested),
        failed_count,
        0,
        (),
        (),
        tuple(durations),
        0,
        healthy=True,
        failure=None,
        shutdown_start_offsets_seconds=tuple(actual_offsets),
        shutdown_inflight=(True,) * len(durations),
        getmore_inflight_at_start=inflight_count,
    )


def _shutdown_worker(
    connection: Connection,
    uri: str,
    configuration: AwaitConfiguration,
    *,
    block: int,
    candidate: int,
    model: ExecutionModel,
) -> None:
    with connection:
        try:
            observation: AwaitWindow | str = asyncio.run(
                run_shutdown(
                    uri, configuration, block=block, candidate=candidate, model=model
                )
            )
        except (BenchmarkSetupError, PyMongoError, TimeoutError) as error:
            observation = (
                str(error)
                if isinstance(error, BenchmarkSetupError)
                else type(error).__name__
            )
        connection.send(observation)


def run_bounded_shutdown(
    uri: str,
    configuration: AwaitConfiguration,
    *,
    block: int,
    candidate: int,
    model: ExecutionModel,
) -> AwaitWindow:
    context = multiprocessing.get_context("spawn")
    reader, writer = context.Pipe(duplex=False)
    process = context.Process(
        target=_shutdown_worker,
        args=(writer, uri, configuration),
        kwargs={"block": block, "candidate": candidate, "model": model},
    )
    with reader, writer:
        process.start()
        writer.close()
        try:
            if not reader.poll(configuration["shutdown_window_timeout_seconds"]):
                raise BenchmarkSetupError(
                    "shutdown window exceeded its registered deadline"
                )
            try:
                observation = reader.recv()
            except EOFError as error:
                raise BenchmarkSetupError(
                    "shutdown measurement process exited without evidence"
                ) from error
            if isinstance(observation, str):
                raise BenchmarkSetupError(observation)
            return cast("AwaitWindow", observation)
        finally:
            if process.is_alive():
                process.kill()
            process.join()
            process.close()


def run_matrix(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or output.with_suffix(".decision.json").exists():
        raise BenchmarkSetupError("use a new output path to preserve retained evidence")
    configuration_bytes = _CONFIG_PATH.read_bytes()
    configuration = load_await_configuration(configuration_bytes)
    digest = configuration_hash(configuration_bytes)
    git_path = shutil.which("git")
    if git_path is None:
        raise BenchmarkSetupError("git is required to record the benchmark revision")
    revision = subprocess.check_output(  # noqa: S603 - fixed git arguments
        [git_path, "rev-parse", "HEAD"], text=True, shell=False
    ).strip()
    environment = {
        "python": platform.python_version(),
        "pymongo": pymongo.version,
        "client_query_cache": version("client-query-cache"),
        "platform": platform.platform(),
    }
    report: dict[str, object] = {
        "schema_version": 1,
        "configuration_sha256": digest,
        "command_count_source": "pymongo_command_listener",
        "scope": "tested_single_member_replica_set_only",
        "client_options": configuration["client_options"],
        "revision": revision,
        "environment": environment,
        "topology": configuration["topology"],
        "samples": [],
    }
    samples: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    report["samples"] = samples
    report["failures"] = failures
    with IsolatedReplicaSet(ResourceLimits(cpus=1, memory="512m")) as replica:
        with MongoClient[dict[str, object]](
            replica.uri, serverSelectionTimeoutMS=10000
        ) as client:
            environment["mongodb"] = client.server_info()["version"]
        for block, candidate, model, workload in planned_windows(configuration):
            try:
                if workload == "shutdown":
                    window = run_bounded_shutdown(
                        replica.uri,
                        configuration,
                        block=block,
                        candidate=candidate,
                        model=model,
                    )
                else:
                    window = asyncio.run(
                        run_window(
                            replica,
                            configuration,
                            block=block,
                            candidate=candidate,
                            model=model,
                            workload=workload,
                        )
                    )
                samples.append(asdict(window))
            except (
                BenchmarkSetupError,
                PyMongoError,
                TimeoutError,
            ) as error:
                failures.append(
                    {
                        "block": block,
                        "candidate_ms": candidate,
                        "model": model,
                        "workload": workload,
                        "error_type": type(error).__name__,
                        "reason": str(error)
                        if isinstance(error, BenchmarkSetupError)
                        else type(error).__name__,
                    }
                )
                print(
                    f"FAILED: block {block + 1} {candidate} ms {model} "
                    f"{workload}: {type(error).__name__}",
                    flush=True,
                )
            output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(
                f"block {block + 1}/6 {candidate} ms {model} {workload}",
                flush=True,
            )

    write_decision(report, configuration, output)


def write_decision(
    report: dict[str, object], configuration: AwaitConfiguration, output: Path
) -> None:
    samples = validate_await_report(
        report, configuration, cast("str", report["configuration_sha256"])
    )
    decision = asdict(evaluate_await_decision(samples, configuration))
    decision["source_report"] = output.name
    decision["report_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    decision["configuration_sha256"] = report["configuration_sha256"]
    decision["revision"] = report["revision"]
    output.with_suffix(".decision.json").write_text(
        json.dumps(decision, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure change-stream await times on an isolated replica set."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate retained measurements and recompute the decision.",
    )
    arguments = parser.parse_args()
    if arguments.validate_only:
        configuration = load_await_configuration(_CONFIG_PATH.read_bytes())
        report = json.loads(arguments.output.read_bytes())
        write_decision(report, configuration, arguments.output)
    else:
        run_matrix(arguments.output)


if __name__ == "__main__":
    main()
