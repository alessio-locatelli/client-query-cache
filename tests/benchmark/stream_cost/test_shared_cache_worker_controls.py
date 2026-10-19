from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.multiprocess_run import WireCommands
from benchmarks.stream_cost.shared_cache import worker
from client_query_cache._types import JsonDict
from client_query_cache.asynchronous.manager import CacheManager as AsyncCacheManager
from client_query_cache.synchronous.manager import CacheManager

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from multiprocessing.connection import Connection

    from benchmarks.stream_cost.shared_cache.owner import FaultableProxy
    from benchmarks.stream_cost.shared_cache.worker import WorkerSpec

pytestmark = pytest.mark.unit


class _FakeProxy:
    __slots__ = ("severed",)

    def __init__(self) -> None:
        self.severed = False

    def sever(self) -> None:
        self.severed = True


class _SyncControl:
    __slots__ = ("received", "sent")

    def __init__(self, requests: tuple[JsonDict, ...]) -> None:
        self.received = list(requests)
        self.sent: list[JsonDict] = []

    def recv(self) -> JsonDict:
        if not self.received:
            raise EOFError
        return self.received.pop(0)

    def send(self, response: JsonDict) -> None:
        self.sent.append(response)


def _context(
    *, manager: object | None = None, proxy: _FakeProxy | None = None
) -> worker._ControlContext:
    spec = cast("WorkerSpec", SimpleNamespace(database="cache_db"))
    return worker._ControlContext(
        spec, manager, cast("FaultableProxy | None", proxy), WireCommands(())
    )


def test_sync_control_applies_snapshot_probe_and_proxy_sever() -> None:
    proxy = _FakeProxy()
    context = _context(proxy=proxy)

    snapshot = worker._apply_sync_control("snapshot", {}, context, lambda _request: {})
    probe = worker._apply_sync_control(
        "probe", {"keys": [1]}, context, lambda request: {"keys": request["keys"]}
    )
    severed = worker._apply_sync_control("sever", {}, context, lambda _request: {})

    assert snapshot["kind"] == "control"
    assert "action_monotonic" not in snapshot
    assert probe["keys"] == [1]
    assert severed["operation"] == "sever"
    assert isinstance(severed["action_monotonic"], float)
    assert proxy.severed


@pytest.mark.parametrize(
    ("operation", "context", "message"),
    [
        pytest.param("sever", _context(), "single-member topology", id="sever"),
        pytest.param(
            "lose-history", _context(), "independent cached worker", id="history"
        ),
        pytest.param("unknown", _context(), "unknown worker control", id="unknown"),
    ],
)
def test_sync_control_rejects_invalid_operations(
    operation: str,
    context: worker._ControlContext,
    message: str,
) -> None:
    with pytest.raises(BenchmarkSetupError, match=message):
        worker._apply_sync_control(operation, {}, context, lambda _request: {})


def test_sync_control_loses_history_for_a_cache_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = object.__new__(CacheManager)
    supervisor = object()
    lost: list[object] = []
    monkeypatch.setattr(
        worker, "independent_sync_supervisor", lambda _manager, _database: supervisor
    )
    monkeypatch.setattr(worker, "lose_sync_stream_history", lost.append)
    monkeypatch.setattr(
        worker,
        "_control_state",
        lambda operation, _context: {"kind": "control", "operation": operation},
    )

    response = worker._apply_sync_control(
        "lose-history", {}, _context(manager=manager), lambda _request: {}
    )

    assert response["operation"] == "lose-history"
    assert isinstance(response["action_monotonic"], float)
    assert lost == [supervisor]


@pytest.mark.parametrize("eof", [False, True], ids=["close", "eof"])
def test_sync_control_server_stops_on_close_or_eof(eof: bool) -> None:
    control = (
        _SyncControl(()) if eof else _SyncControl(({"op": "snapshot"}, {"op": "close"}))
    )

    worker._serve_sync_controls(
        cast("Connection", control), _context(), lambda _request: {}
    )

    assert len(control.sent) == (0 if eof else 1)


class _AsyncControl:
    __slots__ = ("received", "sent")

    def __init__(self, requests: tuple[JsonDict, ...]) -> None:
        self.received = list(requests)
        self.sent: list[JsonDict] = []

    def recv(self) -> JsonDict:
        if not self.received:
            raise EOFError
        return self.received.pop(0)

    def send(self, response: JsonDict) -> None:
        self.sent.append(response)


def test_async_control_server_probes_and_stops_on_close() -> None:
    control = _AsyncControl(
        ({"op": "snapshot"}, {"op": "probe", "keys": [2]}, {"op": "close"})
    )

    async def probe(request: JsonDict) -> JsonDict:
        await asyncio.sleep(0)
        return {"keys": request["keys"]}

    asyncio.run(
        worker._serve_async_controls(
            cast("Connection", control),
            _context(),
            cast("Callable[[JsonDict], Awaitable[JsonDict]]", probe),
        )
    )

    assert [response["operation"] for response in control.sent] == [
        "snapshot",
        "probe",
    ]
    assert control.sent[1]["keys"] == [2]


@pytest.mark.parametrize("eof", [False, True], ids=["close", "eof"])
def test_async_control_server_stops_on_close_or_eof(eof: bool) -> None:
    control = _AsyncControl(()) if eof else _AsyncControl(({"op": "close"},))

    asyncio.run(
        worker._serve_async_controls(
            cast("Connection", control),
            _context(),
            cast("Callable[[JsonDict], Awaitable[JsonDict]]", lambda _request: {}),
        )
    )


@pytest.mark.parametrize(
    ("operation", "context", "message"),
    [
        pytest.param("sever", _context(), "single-member topology", id="sever"),
        pytest.param(
            "lose-history", _context(), "independent cached worker", id="history"
        ),
        pytest.param("unknown", _context(), "unknown worker control", id="unknown"),
    ],
)
def test_async_control_server_rejects_invalid_operations(
    operation: str,
    context: worker._ControlContext,
    message: str,
) -> None:
    with pytest.raises(BenchmarkSetupError, match=message):
        asyncio.run(
            worker._serve_async_controls(
                cast("Connection", _AsyncControl(({"op": operation},))),
                context,
                cast("Callable[[JsonDict], Awaitable[JsonDict]]", lambda _request: {}),
            )
        )


def test_async_control_loses_history_for_an_async_cache_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = object.__new__(AsyncCacheManager)
    supervisor = object()
    lost: list[object] = []
    monkeypatch.setattr(
        worker, "independent_async_supervisor", lambda _manager, _database: supervisor
    )

    async def lose(_supervisor: object) -> None:
        await asyncio.sleep(0)
        lost.append(_supervisor)

    monkeypatch.setattr(worker, "lose_async_stream_history", lose)
    monkeypatch.setattr(
        worker,
        "_control_state",
        lambda operation, _context: {"kind": "control", "operation": operation},
    )
    control = _AsyncControl(({"op": "lose-history"}, {"op": "close"}))

    asyncio.run(
        worker._serve_async_controls(
            cast("Connection", control),
            _context(manager=manager),
            cast("Callable[[JsonDict], Awaitable[JsonDict]]", lambda _request: {}),
        )
    )

    assert len(control.sent) == 1
    assert control.sent[0]["kind"] == "control"
    assert control.sent[0]["operation"] == "lose-history"
    assert isinstance(control.sent[0]["action_monotonic"], float)
    assert lost == [supervisor]


def test_probe_revision_supports_a_common_revision() -> None:
    assert worker._probe_revision({"revision": 4}, 1) == 4
    assert worker._probe_revision({"revisions": {1: 5}}, 1) == 5
