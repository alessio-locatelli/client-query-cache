from __future__ import annotations

import json
import multiprocessing
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from pymongo.errors import ConnectionFailure

from benchmarks.stream_cost import await_run
from benchmarks.stream_cost.errors import BenchmarkSetupError

if TYPE_CHECKING:
    from benchmarks.stream_cost.await_model import AwaitConfiguration

pytestmark = pytest.mark.unit


@pytest.fixture
def configuration() -> AwaitConfiguration:
    return cast(
        "AwaitConfiguration",
        json.loads(Path("reports/stream-cost/await-v1/config.v1.json").read_bytes()),
    )


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        ("timeout", "registered deadline"),
        ("exit", "without evidence"),
        ("error", "failed measurement"),
    ],
)
def test_bounded_shutdown_reaps_worker_on_failure(
    configuration: AwaitConfiguration,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    message: str,
) -> None:
    context = MagicMock()
    reader, writer = MagicMock(), MagicMock()
    context.Pipe.return_value = reader, writer
    reader.poll.return_value = failure != "timeout"
    reader.recv.return_value = "failed measurement"
    if failure == "exit":
        reader.recv.side_effect = EOFError
    process = context.Process.return_value
    process.is_alive.return_value = failure != "exit"
    monkeypatch.setattr(multiprocessing, "get_context", lambda _: context)
    with pytest.raises(BenchmarkSetupError, match=message):
        await_run.run_bounded_shutdown(
            "mongodb://localhost:27017",
            configuration,
            block=0,
            candidate=1000,
            model="sync",
        )
    reader.poll.assert_called_once_with(
        configuration["shutdown_window_timeout_seconds"]
    )
    assert process.kill.call_count == (failure != "exit")
    process.join.assert_called_once_with()
    process.close.assert_called_once_with()
    writer.close.assert_called_once_with()


@pytest.mark.parametrize(
    "error",
    [
        BenchmarkSetupError("measurement failed"),
        ConnectionFailure("private command"),
        TimeoutError(),
    ],
    ids=["measurement", "driver", "timeout"],
)
def test_shutdown_worker_returns_safe_failure_evidence(
    configuration: AwaitConfiguration, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    monkeypatch.setattr(await_run, "run_shutdown", AsyncMock(side_effect=error))
    connection = MagicMock()
    await_run._shutdown_worker(
        connection,
        "mongodb://localhost:27017",
        configuration,
        block=0,
        candidate=1000,
        model="sync",
    )
    expected = (
        str(error) if isinstance(error, BenchmarkSetupError) else type(error).__name__
    )
    connection.send.assert_called_once_with(expected)
