from __future__ import annotations

import asyncio
import errno
import socket
import threading
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict
from unittest.mock import AsyncMock, Mock

import pytest

from benchmarks.stream_cost.shared_cache.protocol import Registration
from benchmarks.stream_cost.shared_cache.window import attachment_for, owner_config
from client_query_cache._shared.attachment import AsyncEndpoint, SyncEndpoint
from client_query_cache._shared.wire import (
    PROTOCOL_VERSION,
    ProtocolError,
    encode_frame,
)

pytestmark = pytest.mark.unit

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Iterator

    from client_query_cache._shared.attachment import AttachmentConfig
    from client_query_cache._shared.coordinator import Message


class ReaderFailure(TypedDict):
    endpoint: AsyncEndpoint
    reader: asyncio.StreamReader
    writer: Mock
    pending: asyncio.Future[Message]


@pytest.fixture
def endpoint(tmp_path: Path) -> AsyncEndpoint:
    registration = Registration.load(Path("reports/shared-worker-cache/v6/config.json"))
    config = owner_config(
        registration,
        "mongodb://localhost",
        str(tmp_path),
        b"test-capability",
        "shared-index",
    )
    return AsyncEndpoint(attachment_for(config))


@pytest.fixture
async def reader_failure(endpoint: AsyncEndpoint) -> AsyncGenerator[ReaderFailure]:
    writer = Mock(spec=asyncio.StreamWriter)
    reader = asyncio.StreamReader()
    pending: asyncio.Future[Message] = asyncio.get_running_loop().create_future()
    endpoint._writer = writer
    endpoint._pending[1] = (writer, pending)
    yield {
        "endpoint": endpoint,
        "reader": reader,
        "writer": writer,
        "pending": pending,
    }
    await endpoint.close()


@pytest.mark.parametrize(
    "error_type",
    [BrokenPipeError, ConnectionResetError],
    ids=["broken-pipe", "connection-reset"],
)
async def test_reader_transport_failure_abandons_pending_requests(
    reader_failure: ReaderFailure,
    error_type: type[ConnectionError],
) -> None:
    endpoint = reader_failure["endpoint"]
    reader_failure["reader"].set_exception(error_type("peer closed the connection"))

    await endpoint._read_loop(reader_failure["reader"], reader_failure["writer"])

    assert endpoint._writer is None
    assert reader_failure["pending"].result() == {"r": "lost"}
    assert endpoint._pending == {}
    reader_failure["writer"].close.assert_called_once()


@pytest.mark.parametrize(
    "error",
    [OSError(errno.ENOTCONN, "transport is not connected"), ConnectionResetError()],
    ids=["not-connected", "reset"],
)
async def test_reconnect_handshake_transport_failure_bypasses_cache(
    endpoint: AsyncEndpoint, monkeypatch: pytest.MonkeyPatch, error: OSError
) -> None:
    reader = asyncio.StreamReader()
    reader.set_exception(error)
    writer = Mock(spec=asyncio.StreamWriter)
    monkeypatch.setattr(
        asyncio, "open_unix_connection", AsyncMock(return_value=(reader, writer))
    )
    assert await endpoint.request({"op": "metadata"}) is None
    assert endpoint.counters.failures == 1
    assert endpoint._writer is None
    assert endpoint._pending == {}
    writer.close.assert_called_once()


async def test_handshake_timeout_reuses_unreachable_owner_backoff(
    endpoint: AsyncEndpoint, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = Mock(spec=asyncio.StreamWriter)
    connect = AsyncMock(return_value=(asyncio.StreamReader(), writer))
    monkeypatch.setattr(asyncio, "open_unix_connection", connect)

    assert await endpoint.request({"op": "metadata"}) is None
    assert await endpoint.request({"op": "metadata"}) is None
    assert endpoint.counters.timeouts == 1
    assert endpoint._writer is None
    assert endpoint._pending == {}
    connect.assert_awaited_once()
    writer.close.assert_called_once()


@pytest.fixture
def incompatible_peer(
    endpoint: AsyncEndpoint, tmp_path: Path
) -> Iterator[AttachmentConfig]:
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    path = tmp_path / "incompatible.sock"
    listener.bind(str(path))
    listener.listen(1)
    listener.settimeout(5)

    def respond() -> None:
        peer, _address = listener.accept()
        with peer:
            peer.recv(65_536)
            peer.sendall(encode_frame({"v": PROTOCOL_VERSION + 1, "id": 0, "r": "ok"}))

    thread = threading.Thread(target=respond, daemon=True)
    thread.start()
    yield replace(endpoint.config, socket_path=str(path))
    listener.close()
    thread.join(5)
    assert not thread.is_alive()


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_incompatible_handshake_is_a_hard_error(
    incompatible_peer: AttachmentConfig, asynchronous: bool
) -> None:
    if asynchronous:
        with pytest.raises(ProtocolError, match="version"):
            await AsyncEndpoint.attach(incompatible_peer, require_owner=False)
    else:
        with pytest.raises(ProtocolError, match="version"):
            SyncEndpoint(incompatible_peer, require_owner=False)
