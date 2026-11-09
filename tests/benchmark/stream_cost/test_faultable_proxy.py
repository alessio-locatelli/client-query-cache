from __future__ import annotations

import socket
import threading
import time
from typing import TYPE_CHECKING

import pytest

from benchmarks.stream_cost.client import BenchmarkClientTopologyConfig, WireCompressor
from benchmarks.stream_cost.proxy import DirectPathProxyConfig
from benchmarks.stream_cost.shared_cache.owner import FaultableProxy
from tests.polling import wait_until

if TYPE_CHECKING:
    from collections.abc import Iterator

    from faker import Faker

    from client_query_cache._types import NonNegativeInt

pytestmark = pytest.mark.unit

_BUFFER_OVERFLOW_BYTES = 200_000
_SOCKET_TIMEOUT_SECONDS = 5.0
_PAUSE_QUIET_SECONDS = 0.2
_HALF_CLOSE_REPLY_BYTES = 64


@pytest.fixture
def upstream_port() -> Iterator[NonNegativeInt]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    served: list[bytes] = []

    def serve() -> None:
        connection, _ = listener.accept()
        with connection:
            received = bytearray()
            while chunk := connection.recv(65_536):
                received.extend(chunk)
            served.append(bytes(received))
            connection.sendall(b"r" * _HALF_CLOSE_REPLY_BYTES)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield listener.getsockname()[1]
    listener.close()
    thread.join(timeout=_SOCKET_TIMEOUT_SECONDS)


@pytest.fixture
def proxy(upstream_port: NonNegativeInt) -> Iterator[FaultableProxy]:
    topology = BenchmarkClientTopologyConfig(
        tls_enabled=False,
        compressor=WireCompressor.NONE,
        discovery_enabled=False,
        shared_connections=False,
    )
    with FaultableProxy(
        DirectPathProxyConfig(topology, "127.0.0.1", upstream_port)
    ) as started:
        yield started


def test_a_half_closed_large_request_is_counted_before_the_reply(
    proxy: FaultableProxy, faker: Faker
) -> None:
    request = faker.binary(length=_BUFFER_OVERFLOW_BYTES)
    with socket.create_connection(("127.0.0.1", proxy.local_port)) as client:
        client.settimeout(_SOCKET_TIMEOUT_SECONDS)
        client.sendall(request)
        client.shutdown(socket.SHUT_WR)
        with client.makefile("rb") as replies:
            assert replies.read() == b"r" * _HALF_CLOSE_REPLY_BYTES

    wait_until(lambda: proxy.bytes_received == _HALF_CLOSE_REPLY_BYTES)
    assert proxy.bytes_sent == len(request)


def test_pause_holds_traffic_until_resume(proxy: FaultableProxy, faker: Faker) -> None:
    request = faker.binary(length=_HALF_CLOSE_REPLY_BYTES)
    proxy.pause()
    with socket.create_connection(("127.0.0.1", proxy.local_port)) as client:
        client.settimeout(_SOCKET_TIMEOUT_SECONDS)
        client.sendall(request)
        client.shutdown(socket.SHUT_WR)
        time.sleep(_PAUSE_QUIET_SECONDS)
        assert proxy.bytes_sent == 0

        proxy.resume()
        with client.makefile("rb") as replies:
            assert replies.read() == b"r" * _HALF_CLOSE_REPLY_BYTES

    wait_until(lambda: proxy.bytes_sent == len(request))


def test_teardown_wakes_senders_that_are_paused(
    proxy: FaultableProxy, faker: Faker
) -> None:
    proxy.pause()
    client = socket.create_connection(("127.0.0.1", proxy.local_port))
    client.sendall(faker.binary(length=_HALF_CLOSE_REPLY_BYTES))
    wait_until(lambda: len(proxy._sockets) == 2)

    proxy.__exit__(None, None, None)

    assert proxy._connection_threads == []
    client.close()


def test_sever_closes_every_connection(proxy: FaultableProxy) -> None:
    with socket.create_connection(("127.0.0.1", proxy.local_port)) as client:
        client.settimeout(_SOCKET_TIMEOUT_SECONDS)
        wait_until(lambda: len(proxy._sockets) == 2)

        proxy.sever()

        assert client.recv(1) == b""
