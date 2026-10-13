from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict
from unittest.mock import Mock

import pytest

from benchmarks.stream_cost.shared_cache.attachment import AsyncEndpoint
from benchmarks.stream_cost.shared_cache.protocol import Registration
from benchmarks.stream_cost.shared_cache.window import attachment_for, owner_config

pytestmark = pytest.mark.unit

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from benchmarks.stream_cost.shared_cache.coordinator import Message


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
