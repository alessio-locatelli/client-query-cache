from __future__ import annotations

import multiprocessing
import secrets
import socket
import threading
from typing import TYPE_CHECKING

import pytest

from benchmarks.stream_cost.shared_cache.attachment import SyncEndpoint
from benchmarks.stream_cost.shared_cache.coordinator import (
    OwnerConfig,
    SharedCacheOwner,
)
from benchmarks.stream_cost.shared_cache.window import attachment_for
from benchmarks.stream_cost.shared_cache.wire import encode_frame
from tests.shared_cache.conftest import LIMITS, wait_for

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from benchmarks.stream_cost.shared_cache.attachment import Message

pytestmark = pytest.mark.unit

_DATABASE = "unreachable"


@pytest.fixture
def owner(socket_directory: Path) -> Iterator[SharedCacheOwner]:
    config = OwnerConfig(
        socket_path=str(socket_directory / "owner.sock"),
        capability=secrets.token_bytes(32),
        mongodb_uri="mongodb://127.0.0.1:9/?directConnection=true",
        client_options={"serverSelectionTimeoutMS": 100},
        databases=(_DATABASE,),
        budget_bytes=1024 * 1024,
        max_entry_bytes=64 * 1024,
        max_await_time_ms=100,
        limits=LIMITS,
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
