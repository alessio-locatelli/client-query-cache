from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from typing import IO, TYPE_CHECKING

import pytest

from benchmarks.public_shared_cache import _process_cpu_clock
from client_query_cache._types import PositiveFloat

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit
_SHUTDOWN_TIMEOUT_SECONDS: PositiveFloat = 5.0


@dataclass(slots=True)
class CpuProbe:
    process: subprocess.Popen[str]
    commands: IO[str]
    observations: IO[str]


@pytest.fixture
def cpu_probe() -> Iterator[CpuProbe]:
    program = """import sys, time
print(time.process_time_ns(), flush=True)
for line in sys.stdin:
    print(time.process_time_ns(), flush=True)
"""
    with subprocess.Popen(  # noqa: S603 - Execute this interpreter with a fixed, local CPU probe.
        (sys.executable, "-c", program),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    ) as process:
        assert process.stdin is not None
        assert process.stdout is not None
        assert int(process.stdout.readline()) > 0
        yield CpuProbe(process, process.stdin, process.stdout)
        process.stdin.close()
        process.wait(timeout=_SHUTDOWN_TIMEOUT_SECONDS)


def test_foreign_process_clock_matches_its_own_cpu(cpu_probe: CpuProbe) -> None:
    clock = _process_cpu_clock(cpu_probe.process.pid)
    before = time.clock_gettime_ns(clock)
    cpu_probe.commands.write("sample\n")
    cpu_probe.commands.flush()
    reported = int(cpu_probe.observations.readline())
    after = time.clock_gettime_ns(clock)
    assert before <= reported <= after
    assert after > before
    assert time.clock_getres(clock) == time.get_clock_info("process_time").resolution


def test_foreign_process_clock_reports_a_stopped_owner(cpu_probe: CpuProbe) -> None:
    cpu_probe.commands.close()
    cpu_probe.process.wait(timeout=_SHUTDOWN_TIMEOUT_SECONDS)
    with pytest.raises(ProcessLookupError):
        _process_cpu_clock(cpu_probe.process.pid)
