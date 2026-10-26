from __future__ import annotations

import asyncio
import multiprocessing
import os
import time
from contextlib import nullcontext
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Self, assert_never, cast, override

from pymongo import AsyncMongoClient
from pymongo.errors import OperationFailure, PyMongoError

from benchmarks.stream_cost.multiprocess_run import WireCommands
from benchmarks.stream_cost.shared_cache.owner import proxy_for
from client_query_cache._types import (
    BsonDict,
    NonEmpty,
    NonEmptyStr,
    NonNegativeInt,
    PositiveFloat,
)
from client_query_cache.asynchronous.manager import CacheManager

if TYPE_CHECKING:
    import socket
    from collections.abc import Callable, Mapping
    from multiprocessing.connection import Connection
    from multiprocessing.context import SpawnContext
    from multiprocessing.process import BaseProcess

    from pymongo.asynchronous.collection import AsyncCollection
    from pymongo.monitoring import CommandFailedEvent, CommandStartedEvent

    from benchmarks.stream_cost.shared_cache.owner import FaultableProxy
    from client_query_cache.asynchronous.collection import CachedCollection
    from client_query_cache.asynchronous.streams import (
        DatabaseStreamSupervisor as AsyncDatabaseStreamSupervisor,
    )

    type WorkerCollection = AsyncCollection[BsonDict] | CachedCollection[BsonDict]

type Payload = dict[str, object]
type WorkerPath = Literal["direct", "independent"]
type TcpFault = Literal["sever", "sever-on-poll"]
type WorkerOperation = Literal["lose-history", "read", "snapshot"] | TcpFault
type Operation = Literal["close"] | WorkerOperation

_HISTORY_LOST = 286
_POLL_SECONDS = 0.05
_WORKER_TIMEOUT_SECONDS = 30.0
_SHUTDOWN_SECONDS = 5.0


class WorkerCommands(WireCommands):
    def __init__(self, collections: tuple[NonEmptyStr, ...]) -> None:
        super().__init__(collections)
        self._pending_sever: tuple[FaultableProxy, asyncio.Future[None]] | None = None
        self._severed_sockets: tuple[socket.socket, ...] = ()
        self.poll_cuts: NonNegativeInt = 0

    async def sever_during_poll(
        self, proxy: FaultableProxy, *, cut_immediately: bool
    ) -> NonNegativeInt:
        severed: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._severed_sockets = ()
        self.poll_cuts = 0
        self._pending_sever = (proxy, severed)
        try:
            if cut_immediately:
                self._severed_sockets = _sever_established_proxy_sockets(proxy)
            await asyncio.wait_for(asyncio.shield(severed), _SHUTDOWN_SECONDS)
            return await _await_socket_closure(self._severed_sockets)
        finally:
            self._pending_sever = None

    @override
    def started(self, event: CommandStartedEvent) -> None:
        super().started(event)
        if event.command_name == "getMore" and self._pending_sever is not None:
            proxy, _ = self._pending_sever
            # The driver has checked out this poll's socket but has not sent it.
            self._severed_sockets += _sever_established_proxy_sockets(proxy)
            self.poll_cuts += 1

    @override
    def failed(self, event: CommandFailedEvent) -> None:
        super().failed(event)
        if event.command_name == "getMore" and self._pending_sever is not None:
            _, severed = self._pending_sever
            self._pending_sever = None
            severed.set_result(None)


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    uri: str
    database: str
    collection: str
    identity: NonNegativeInt
    path: WorkerPath
    proxy_enabled: bool


@dataclass(frozen=True, slots=True)
class WorkerRuntime:
    manager: CacheManager[BsonDict] | None
    collection: WorkerCollection
    config: WorkerConfig
    listener: WorkerCommands
    proxy: FaultableProxy | None


class WorkerProcesses:
    __slots__ = ("_configs", "_connections", "_context", "_processes")

    def __init__(self, configs: tuple[WorkerConfig, ...]) -> None:
        self._context: SpawnContext = multiprocessing.get_context("spawn")
        self._configs = configs
        self._connections: list[Connection | None] = [None] * len(configs)
        self._processes: list[BaseProcess | None] = [None] * len(configs)

    def __enter__(self) -> Self:
        try:
            for index in range(len(self._configs)):
                self._start(index)
        except BaseException:  # pragma: no cover (failed startup must still clean up).
            self._stop()
            raise
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self._stop()

    def request(self, index: NonNegativeInt, operation: Operation) -> Payload:
        connection = self._connections[index]
        assert connection is not None
        connection.send({"op": operation})
        response = self._receive(index)
        if response["kind"] == "error":  # pragma: lax no cover (network timing varies).
            raise WorkerRequestError(str(response["error"]))
        assert response["kind"] == "result"
        return response

    def restart(self, index: NonNegativeInt) -> Payload:
        process = self._processes[index]
        connection = self._connections[index]
        assert process is not None
        assert connection is not None
        process.kill()
        process.join(_SHUTDOWN_SECONDS)
        if process.is_alive():  # pragma: no cover (SIGKILL should end the process).
            message = f"worker {index} did not exit after kill"
            raise AssertionError(message)
        connection.close()
        return self._start(index)

    def _start(self, index: NonNegativeInt) -> Payload:
        parent, child = self._context.Pipe()
        process = self._context.Process(
            target=_worker_main, args=(self._configs[index], child)
        )
        process.start()
        child.close()
        self._connections[index] = parent
        self._processes[index] = process
        response = self._receive(index)
        if response["kind"] == "error":  # pragma: no cover (startup fault is external).
            raise AssertionError(str(response["error"]))
        assert response["kind"] == "ready"
        return response

    def _receive(self, index: NonNegativeInt) -> Payload:
        connection = self._connections[index]
        assert connection is not None
        if not connection.poll(  # pragma: no cover (timeout fails the test).
            _WORKER_TIMEOUT_SECONDS
        ):
            message = f"worker {index} startup or request timed out"
            raise AssertionError(message)
        try:
            return cast("Payload", connection.recv())
        except (
            EOFError
        ) as error:  # pragma: no cover (a clean worker replies before exit).
            message = f"worker {index} exited before responding"
            raise AssertionError(message) from error

    def _stop(self) -> None:
        for process, connection in zip(self._processes, self._connections, strict=True):
            if process is None:  # pragma: no cover (partial startup failure only).
                continue
            if (
                process.is_alive() and connection is not None
            ):  # pragma: lax no cover (exit timing varies).
                try:
                    connection.send({"op": "close"})
                except (
                    BrokenPipeError
                ):  # pragma: no cover (worker control pipe is open).
                    pass
            process.join(_SHUTDOWN_SECONDS)
            if (
                process.is_alive()
            ):  # pragma: no cover (shutdown timeout is a test failure).
                process.kill()
                process.join(_SHUTDOWN_SECONDS)
            if (
                connection is not None
            ):  # pragma: no cover (partial startup failure only).
                connection.close()


class WorkerRequestError(AssertionError):
    pass


async def _lose_async_stream_history(
    manager: CacheManager[BsonDict], database: str
) -> NonNegativeInt:
    supervisor = manager._coordinator._supervisors[database]
    assert supervisor._resume_token is not None
    supervisor_type = type(supervisor)
    original = supervisor_type._open_stream
    injected = asyncio.Event()

    async def unresumable(
        _instance: AsyncDatabaseStreamSupervisor,
        *,
        resume_token: Mapping[str, object] | None,
        use_start_after: bool,
    ) -> None:
        del use_start_after
        assert resume_token is not None
        supervisor_type._open_stream = original  # type: ignore[method-assign]
        injected.set()
        await asyncio.sleep(0)
        raise OperationFailure("history lost", code=_HISTORY_LOST)

    supervisor_type._open_stream = unresumable  # type: ignore[method-assign,assignment]
    stream = supervisor._stream
    assert stream is not None
    await stream.close()
    await asyncio.wait_for(injected.wait(), timeout=_WORKER_TIMEOUT_SECONDS)
    deadline = time.monotonic() + _WORKER_TIMEOUT_SECONDS
    while (
        manager.snapshot().entry_count != 0
        or manager.stream_health_snapshot(database).status.value != "healthy"
    ):
        if time.monotonic() >= deadline:
            raise TimeoutError(  # pragma: no cover (recovery timeout fails the test).
                "history-loss recovery did not clear and reopen the stream"
            )
        await asyncio.sleep(_POLL_SECONDS)
    return _HISTORY_LOST


def _worker_main(config: WorkerConfig, control: Connection) -> None:
    asyncio.run(_run_worker(config, control))


async def _run_worker(config: WorkerConfig, control: Connection) -> None:
    proxy_context = proxy_for(config.uri) if config.proxy_enabled else nullcontext(None)
    with proxy_context as proxy:
        uri = config.uri
        if proxy is not None:
            uri = f"mongodb://127.0.0.1:{proxy.local_port}/?directConnection=true"
        listener = WorkerCommands((config.collection,))
        client = AsyncMongoClient[BsonDict](
            uri, serverSelectionTimeoutMS=1_000, event_listeners=[listener]
        )
        manager: CacheManager[BsonDict] | None = None
        try:
            manager, collection = await _open_worker(client, config)
            await _send_state(control, "ready", manager, config, listener)
            await _serve_worker(
                control,
                WorkerRuntime(manager, collection, config, listener, proxy),
            )
        except (
            PyMongoError
        ) as error:  # pragma: lax no cover (startup failure timing varies).
            await _send_error(control, type(error).__name__)
        except (
            TimeoutError
        ) as error:  # pragma: no cover (expired readiness is a test failure).
            await _send_error(control, str(error))
        finally:
            if manager is not None:
                await manager.close()
            await client.close()


async def _open_worker(
    client: AsyncMongoClient[BsonDict], config: WorkerConfig
) -> tuple[CacheManager[BsonDict] | None, WorkerCollection]:
    await client.admin.command("ping")
    manager: CacheManager[BsonDict] | None = None
    collection: WorkerCollection
    if config.path == "independent":
        manager = CacheManager(client)
        collection = manager[config.database][config.collection]
    else:
        collection = client[config.database][config.collection]
    await collection.find_one({"_id": config.identity})
    if manager is not None:
        deadline = time.monotonic() + _WORKER_TIMEOUT_SECONDS
        while (
            manager.stream_health_snapshot(config.database).status.value != "healthy"
        ):  # pragma: lax no cover (stream startup timing varies).
            if time.monotonic() >= deadline:
                raise TimeoutError(  # pragma: no cover (expiry fails setup).
                    "cache worker stream did not become healthy"
                )
            await asyncio.sleep(_POLL_SECONDS)
    return manager, collection


async def _serve_worker(
    control: Connection,
    runtime: WorkerRuntime,
) -> None:
    while True:
        request = cast("Payload", await asyncio.to_thread(control.recv))
        operation = cast("Operation", request["op"])
        if operation == "close":
            return
        try:
            response = await _handle_operation(operation, runtime)
        except (
            PyMongoError
        ) as error:  # pragma: lax no cover (transient read timing varies).
            response = {"kind": "error", "error": type(error).__name__}
        await asyncio.to_thread(control.send, response)


async def _handle_operation(
    operation: WorkerOperation,
    runtime: WorkerRuntime,
) -> Payload:
    manager = runtime.manager
    config = runtime.config
    listener = runtime.listener
    match operation:
        case "snapshot":
            return _state("result", manager, config, listener)
        case "read":
            document = await runtime.collection.find_one({"_id": config.identity})
            state = _state("result", manager, config, listener)
            state["revision"] = None if document is None else document["revision"]
            return state
        case "sever" | "sever-on-poll":
            proxy = runtime.proxy
            assert proxy is not None
            severed_sockets = (
                await _await_socket_closure(_sever_established_proxy_sockets(proxy))
                if manager is None
                else await listener.sever_during_poll(
                    proxy, cut_immediately=operation == "sever"
                )
            )
            state = _state("result", manager, config, listener)
            state["severed_sockets"] = severed_sockets
            state["poll_cuts"] = listener.poll_cuts
            return state
        case "lose-history":
            assert manager is not None
            error_code = await _lose_async_stream_history(manager, config.database)
            state = _state("result", manager, config, listener)
            state["history_fault_code"] = error_code
            return state
    assert_never(operation)


def _sever_established_proxy_sockets(
    proxy: FaultableProxy,
) -> NonEmpty[tuple[socket.socket, ...]]:
    with proxy._lock:
        sockets = tuple(sock for sock in proxy._sockets if sock.fileno() >= 0)
    if not sockets:
        raise AssertionError("worker has no established MongoDB TCP sockets to sever")
    proxy.sever()
    return sockets


async def _await_socket_closure(
    sockets: NonEmpty[tuple[socket.socket, ...]],
) -> NonNegativeInt:
    deadline = time.monotonic() + _SHUTDOWN_SECONDS
    while any(sock.fileno() >= 0 for sock in sockets):
        if time.monotonic() >= deadline:
            raise TimeoutError(  # pragma: no cover (socket timeout fails the test).
                "severed MongoDB TCP sockets did not close"
            )
        await asyncio.sleep(_POLL_SECONDS)
    return len(sockets)


async def _send_state(
    control: Connection,
    kind: str,
    manager: CacheManager[BsonDict] | None,
    config: WorkerConfig,
    listener: WorkerCommands,
) -> None:
    await asyncio.to_thread(control.send, _state(kind, manager, config, listener))


async def _send_error(  # pragma: no cover (only used for worker startup failures).
    control: Connection, error: str
) -> None:
    await asyncio.to_thread(control.send, {"kind": "error", "error": error})


def _state(
    kind: str,
    manager: CacheManager[BsonDict] | None,
    config: WorkerConfig,
    listener: WorkerCommands,
) -> Payload:
    try:
        failed_polls = listener.snapshot()["getMore:failed"]
    except KeyError:
        failed_polls = 0
    if manager is None:
        return {
            "kind": kind,
            "pid": os.getpid(),
            "entries": 0,
            "hits": 0,
            "misses": 0,
            "invalidations": 0,
            "health": None,
            "streams": listener.streams,
            "failed_polls": failed_polls,
        }
    snapshot = manager.snapshot()
    telemetry = manager.stream_cost_snapshot(config.database)
    return {
        "kind": kind,
        "pid": os.getpid(),
        "entries": snapshot.entry_count,
        "hits": snapshot.hits,
        "misses": snapshot.misses,
        "invalidations": telemetry.invalidations,
        "health": manager.stream_health_snapshot(config.database).status.value,
        "streams": listener.streams,
        "failed_polls": failed_polls,
    }


def wait_for(
    workers: WorkerProcesses,
    index: NonNegativeInt,
    predicate: Callable[[Payload], bool],
    *,
    timeout: PositiveFloat = _WORKER_TIMEOUT_SECONDS,
) -> Payload:
    deadline = time.monotonic() + timeout
    last: Payload = {}
    while time.monotonic() < deadline:
        try:
            last = workers.request(index, "snapshot")
        except (
            WorkerRequestError
        ):  # pragma: lax no cover (transient read timing varies).
            time.sleep(_POLL_SECONDS)
            continue
        if predicate(last):
            return last
        time.sleep(
            _POLL_SECONDS
        )  # pragma: lax no cover (the requested state may be immediate).
    message = (  # pragma: no cover (the state deadline fails the test).
        f"worker {index} did not reach the requested state: {last}"
    )
    raise AssertionError(message)  # pragma: no cover (the requested state is required).
