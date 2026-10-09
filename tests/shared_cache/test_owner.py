from __future__ import annotations

import multiprocessing
import secrets
import socket
import struct
import threading
import time
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from benchmarks.stream_cost.shared_cache.attachment import SyncEndpoint
from benchmarks.stream_cost.shared_cache.coordinator import (
    OwnerConfig,
    SharedCacheOwner,
)
from benchmarks.stream_cost.shared_cache.window import attachment_for
from benchmarks.stream_cost.shared_cache.wire import encode_frame, encode_key
from tests.shared_cache.conftest import LIMITS, wait_for

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from benchmarks.stream_cost.shared_cache.attachment import Message

pytestmark = pytest.mark.unit

_DATABASE = "unreachable"


@pytest.fixture
def owner(
    socket_directory: Path, request: pytest.FixtureRequest
) -> Iterator[SharedCacheOwner]:
    limits = getattr(request, "param", {})
    config = OwnerConfig(
        socket_path=str(socket_directory / "owner.sock"),
        capability=secrets.token_bytes(32),
        mongodb_uri="mongodb://127.0.0.1:9/?directConnection=true",
        client_options={"serverSelectionTimeoutMS": 100},
        databases=(_DATABASE,),
        budget_bytes=1024 * 1024,
        max_entry_bytes=64 * 1024,
        max_await_time_ms=100,
        limits=replace(LIMITS, **limits),
        lag_capture=(1, 1, 0),
    )
    instance = SharedCacheOwner(config)
    instance.bind()
    parent, child = multiprocessing.Pipe()
    serving = threading.Thread(
        target=instance.serve, args=(child, lambda _request: {"ok": True})
    )
    serving.start()
    yield instance
    parent.send("close")
    serving.join(10)
    instance.close()


def _metadata(endpoint: SyncEndpoint) -> Message | None:
    return endpoint.request({"op": "metadata", "ns": [_DATABASE, "catalogue"]})


def test_failed_stream_activation_bypasses_and_retries(
    owner: SharedCacheOwner,
) -> None:
    endpoint = SyncEndpoint(attachment_for(owner.config))

    first = _metadata(endpoint)
    wait_for(lambda: owner._activation[_DATABASE][0] == "failed")
    held = _metadata(endpoint)
    wait_for(
        lambda: (
            _metadata(endpoint) is not None
            and owner._activation[_DATABASE][0] == "pending"
        )
    )

    assert first is not None
    assert held is not None
    assert first["reason"] == held["reason"] == "stream-starting"
    endpoint.close()


def test_a_second_owner_cannot_bind_a_held_endpoint(owner: SharedCacheOwner) -> None:
    contender = SharedCacheOwner(owner.config)

    with pytest.raises(RuntimeError, match="already holds this endpoint"):
        contender.bind()
    contender.close()


def test_a_peer_that_disappears_before_its_reply_is_detached(
    owner: SharedCacheOwner,
) -> None:
    peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    peer.connect(owner.config.socket_path)
    peer.sendall(encode_frame(attachment_for(owner.config).hello()))
    peer.close()

    wait_for(
        lambda: owner.counters.connections_accepted == 1 and not owner._connections
    )


def _activate(owner: SharedCacheOwner) -> None:
    owner._activation[_DATABASE] = ("active", time.monotonic())
    owner.progress.observed[_DATABASE] = time.monotonic() + 3600


def _select_find(**changes: object) -> Message:
    return {
        "op": "select-find",
        "ns": [_DATABASE, "catalogue"],
        "epoch": 0,
        "family": encode_key("family"),
        "limit": 4,
        **changes,
    }


def _authenticated(owner: SharedCacheOwner) -> socket.socket:
    peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    peer.settimeout(5)
    peer.connect(owner.config.socket_path)
    peer.sendall(encode_frame(attachment_for(owner.config).hello()))
    _read_reply(peer)
    return peer


def _read_reply(peer: socket.socket) -> bytes:
    (length,) = struct.unpack("<I", _read_exactly(peer, 4))
    return _read_exactly(peer, length)


def _read_exactly(peer: socket.socket, size: int) -> bytes:
    received = b""
    while len(received) < size:
        chunk = peer.recv(size - len(received))
        assert chunk
        received += chunk
    return received


def test_selection_reports_unavailable_streams_and_stale_epochs(
    owner: SharedCacheOwner,
) -> None:
    _activate(owner)
    endpoint = SyncEndpoint(attachment_for(owner.config))

    stale = endpoint.request(_select_find(epoch=7))
    owner.core.set_database_available(_DATABASE, available=False)
    unavailable = endpoint.request(_select_find())

    assert stale is not None
    assert stale["r"] == "refresh"
    assert unavailable is not None
    assert unavailable["reason"] == "stream-unavailable"
    endpoint.close()


@pytest.mark.parametrize(
    "message",
    [
        pytest.param(_select_find(limit="four"), id="find-limit"),
        pytest.param({"op": "rename", "ns": [_DATABASE, "catalogue"]}, id="operation"),
    ],
)
def test_invalid_requests_after_the_gate_detach_the_peer(
    owner: SharedCacheOwner, message: Message
) -> None:
    _activate(owner)
    peer = _authenticated(owner)

    peer.sendall(encode_frame({"v": 1, "id": 2, **message}))

    assert peer.recv(1) == b""
    assert owner.counters.protocol_errors == 1
    peer.close()


def test_split_frames_are_reassembled(owner: SharedCacheOwner) -> None:
    peer = _authenticated(owner)
    frame = encode_frame({"v": 1, "id": 2, "op": "observe"})

    peer.sendall(frame[:3])
    time.sleep(0.1)
    peer.sendall(frame[3:10])
    time.sleep(0.1)
    peer.sendall(frame[10:])

    assert b"group" in _read_reply(peer)
    peer.close()


def test_a_reader_that_falls_behind_receives_every_queued_reply(
    owner: SharedCacheOwner,
) -> None:
    peer = _authenticated(owner)
    peer.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4_096)
    replies = 200

    for request_id in range(replies):
        peer.sendall(encode_frame({"v": 1, "id": request_id, "op": "observe"}))
    time.sleep(0.3)
    received = [_read_reply(peer) for _ in range(replies)]

    assert len(received) == replies
    assert owner.counters.detached == 0
    peer.close()


@pytest.mark.parametrize("owner", [{"capture_seconds": 0.2}], indirect=True)
def test_capture_expiry_releases_handles_of_each_session(
    owner: SharedCacheOwner,
) -> None:
    _activate(owner)
    endpoints = [SyncEndpoint(attachment_for(owner.config)) for _ in range(2)]

    replies = [endpoint.request(_select_find()) for endpoint in endpoints]
    wait_for(lambda: owner.counters.expired_captures == 2)

    assert all(reply is not None and reply["r"] == "miss" for reply in replies)
    assert not owner._handles
    for endpoint in endpoints:
        endpoint.close()
