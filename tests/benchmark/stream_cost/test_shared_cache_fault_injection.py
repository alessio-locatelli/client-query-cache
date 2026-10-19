from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pymongo.errors import OperationFailure

from benchmarks.stream_cost.shared_cache.fault_injection import (
    independent_sync_supervisor,
    lose_sync_stream_history,
)

pytestmark = pytest.mark.unit


class _FakeStream:
    __slots__ = ("supervisor",)

    def __init__(self, supervisor: _FakeSupervisor) -> None:
        self.supervisor = supervisor

    def close(self) -> None:
        self.supervisor._open_stream(resume_token=None, use_start_after=False)


class _FakeSupervisor:
    __slots__ = ("_stream",)

    _open_stream = Mock()

    def __init__(self) -> None:
        self._stream = _FakeStream(self)


def test_sync_history_loss_is_one_shot_and_reports_server_history_error() -> None:
    supervisor = _FakeSupervisor()
    original = _FakeSupervisor._open_stream

    with pytest.raises(OperationFailure, match="history lost") as error:
        lose_sync_stream_history(supervisor)  # type: ignore[arg-type]

    assert error.value.code == 286
    assert _FakeSupervisor._open_stream is original


def test_independent_sync_supervisor_selects_the_database_owner() -> None:
    supervisor = object()
    manager = SimpleNamespace(
        _coordinator=SimpleNamespace(_supervisors={"cache_db": supervisor})
    )

    assert independent_sync_supervisor(manager, "cache_db") is supervisor  # type: ignore[arg-type]
