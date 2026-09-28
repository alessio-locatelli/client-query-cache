from __future__ import annotations

from datetime import timedelta
from unittest.mock import Mock

import pytest
from pymongo.monitoring import (
    CommandFailedEvent,
    CommandStartedEvent,
    CommandSucceededEvent,
)

from benchmarks.stream_cost.await_commands import AwaitCommandListener

pytestmark = pytest.mark.unit

_CONNECTION = ("localhost", 27017)
_REQUEST_ID = 1
_AWAIT_TIME_MS = 1_000


@pytest.fixture
def listener() -> AwaitCommandListener:
    return AwaitCommandListener()


@pytest.mark.parametrize("failed", [False, True], ids=["success", "failure"])
def test_records_only_command_timing_and_requested_wait(
    listener: AwaitCommandListener, *, failed: bool
) -> None:
    listener.started(
        CommandStartedEvent(
            {"getMore": 123, "collection": "measured", "maxTimeMS": _AWAIT_TIME_MS},
            "benchmark",
            _REQUEST_ID,
            _CONNECTION,
            None,
        )
    )
    pending = listener.snapshot()
    assert len(pending) == 1
    assert pending[0].completed_seconds is None
    assert pending[0].max_time_ms == _AWAIT_TIME_MS

    if failed:
        listener.failed(
            CommandFailedEvent(
                timedelta(milliseconds=1), {}, "getMore", _REQUEST_ID, _CONNECTION, None
            )
        )
    else:
        listener.succeeded(
            CommandSucceededEvent(
                timedelta(milliseconds=1), {}, "getMore", _REQUEST_ID, _CONNECTION, None
            )
        )
    completed = listener.snapshot()[0]
    assert completed.completed_seconds is not None
    assert completed.completed_seconds >= completed.started_seconds
    assert completed.failed is failed
    assert pending[0].completed_seconds is None


def test_ignores_other_commands(listener: AwaitCommandListener) -> None:
    listener.started(CommandStartedEvent({"ping": 1}, "admin", 0, _CONNECTION, None))
    listener.succeeded(
        CommandSucceededEvent(timedelta(), {}, "ping", 0, _CONNECTION, None)
    )
    listener.failed(CommandFailedEvent(timedelta(), {}, "ping", 0, _CONNECTION, None))
    assert listener.snapshot() == ()


def test_records_missing_wait(listener: AwaitCommandListener) -> None:
    listener.started(
        CommandStartedEvent({"getMore": 123}, "benchmark", 0, _CONNECTION, None)
    )
    assert listener.snapshot()[0].max_time_ms is None


def test_wait_times_out_without_a_command_boundary(
    listener: AwaitCommandListener,
) -> None:
    with pytest.raises(TimeoutError, match="no getMore boundary"):
        listener.wait_for_change(listener.version, 0.001)


def test_wait_observes_an_already_changed_version(
    listener: AwaitCommandListener,
) -> None:
    previous = listener.version
    listener.started(
        CommandStartedEvent({"getMore": 123}, "benchmark", 0, _CONNECTION, None)
    )
    listener.wait_for_change(previous, 1)
    assert listener.version > previous


def test_boundary_callback_runs_once_before_command_is_recorded(
    listener: AwaitCommandListener,
) -> None:
    snapshots = []
    callback = Mock(side_effect=lambda: snapshots.append(listener.snapshot()))
    listener.at_next_start(callback)
    for request_id in (1, 2):
        listener.started(
            CommandStartedEvent(
                {"getMore": 123}, "benchmark", request_id, _CONNECTION, None
            )
        )
    callback.assert_called_once_with()
    assert snapshots == [()]
    assert len(listener.snapshot()) == 2
