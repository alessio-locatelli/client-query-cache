from __future__ import annotations

import multiprocessing
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

import psutil
import pytest

from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.shared_cache import window
from benchmarks.stream_cost.shared_cache.protocol import Registration, smoke_cells
from benchmarks.stream_cost.shared_cache.worker import _query, _verify

if TYPE_CHECKING:
    from benchmarks.stream_cost.shared_cache.protocol import Payload
    from benchmarks.stream_cost.shared_cache.worker import WorkerSpec

pytestmark = pytest.mark.unit

_CONFIG = Path("reports/shared-worker-cache/v3/config.json")


@pytest.fixture
def registration() -> Registration:
    return Registration.load(_CONFIG)


class _SilentControl:
    __slots__ = ("sent",)

    def __init__(self) -> None:
        self.sent: list[object] = []

    def send(self, request: object) -> None:
        self.sent.append(request)

    @staticmethod
    def poll(_timeout: float) -> bool:
        return False


class _BrokenControl:
    __slots__ = ("closed",)

    def __init__(self) -> None:
        self.closed = False

    @staticmethod
    def send(_request: object) -> None:
        raise BrokenPipeError

    def close(self) -> None:
        self.closed = True


class _LingeringProcess:
    __slots__ = ("joined",)

    def __init__(self) -> None:
        self.joined = False

    @staticmethod
    def is_alive() -> bool:
        return True

    def join(self, _timeout: float) -> None:
        self.joined = True

    @staticmethod
    def terminate() -> None:
        return None

    @staticmethod
    def kill() -> None:
        return None


@pytest.fixture
def group() -> window.ProcessGroup:
    return window.ProcessGroup(multiprocessing.get_context("spawn"), 0.1)


def test_memory_sampling_reports_a_vanished_process() -> None:
    sampler = window.GroupMemorySampler({"worker-0": 2**22 + 12_345}, 0.01)

    with sampler:
        time.sleep(0.05)

    with pytest.raises(BenchmarkSetupError, match="PSS sampling failed"):
        sampler.summary()


def test_memory_summary_requires_a_sample() -> None:
    sampler = window.GroupMemorySampler({"harness": psutil.Process().pid}, 1.0)

    with pytest.raises(BenchmarkSetupError, match="no group PSS sample"):
        sampler.summary()


def test_find_profiles_schedule_category_reads(registration: Registration) -> None:
    cell = replace(smoke_cells(registration)[0], profile="find16")

    workload = window._workload(registration, cell)

    assert (workload.read, workload.limit) == ("find", 16)
    assert sorted(workload.keys) == list(range(64))


def test_an_unanswered_owner_request_fails_the_window(
    group: window.ProcessGroup,
) -> None:
    group.owner_control = _SilentControl()  # type: ignore[assignment]

    with pytest.raises(BenchmarkSetupError, match="did not answer in time"):
        group.owner_request({"op": "sample"}, time.monotonic() + 0.01)


def test_cleanup_tolerates_a_closed_owner_pipe(group: window.ProcessGroup) -> None:
    control = _BrokenControl()
    process = _LingeringProcess()
    group.owner_control = control  # type: ignore[assignment]
    group.owner = process  # type: ignore[assignment]

    with pytest.raises(BenchmarkSetupError, match="children remain alive"):
        group.__exit__()

    assert control.closed
    assert process.joined


def test_ready_checks_reject_unexpected_stream_ownership(
    registration: Registration, group: window.ProcessGroup
) -> None:
    cell = next(cell for cell in smoke_cells(registration) if cell.path == "direct")
    workload = window._workload(registration, cell)
    ready: list[Payload] = [
        {"entries": None, "streams": 1},
        {"entries": None, "streams": 0},
    ]

    with pytest.raises(BenchmarkSetupError, match="stream ownership"):
        window._verify_ready(group, cell, workload, ready, time.monotonic() + 1)


class _ShiftedCalibration:
    __slots__ = ()

    @staticmethod
    def exceeds_drift_tolerance(_tolerance: float) -> bool:
        return True


def test_active_windows_reject_clock_changes(registration: Registration) -> None:
    cell = next(cell for cell in smoke_cells(registration) if cell.workload == "active")

    with pytest.raises(BenchmarkSetupError, match="clock or primary changed"):
        window._check_clock(registration, cell, _ShiftedCalibration())  # type: ignore[arg-type]


def test_failed_worker_commands_reject_the_window() -> None:
    samples: list[Payload] = [{"commands": {"find:completed": 3, "find:failed": 1}}]

    with pytest.raises(BenchmarkSetupError, match="failed wire command"):
        window.reject_failed_commands(samples)


@dataclass(frozen=True, slots=True)
class _Spec:
    read: str
    limit: int


def test_sorted_find_results_must_be_complete() -> None:
    spec = cast("WorkerSpec", _Spec("find", 16))

    query, options = _query(spec, 3)

    assert query == {"attributes.category": 3}
    assert options == {"sort": [("_id", 1)], "limit": 16}
    with pytest.raises(LookupError, match="incomplete result"):
        _verify(spec, [{"payload": "", "revision": 0}])
