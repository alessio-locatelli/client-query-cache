from __future__ import annotations

import time

import pytest

from tests.benchmark.real_server import workers

pytestmark = pytest.mark.unit

_PING_SLEEP_SECONDS = 0.05


def test_run_preflight_and_start_clock_excludes_the_ping_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _slow_ping(uri: str) -> None:
        assert uri == "mongodb://fake"
        time.sleep(_PING_SLEEP_SECONDS)

    monkeypatch.setattr(workers, "preflight_ping", _slow_ping)
    before = time.perf_counter()

    start = workers.run_preflight_and_start_clock("mongodb://fake")

    after = time.perf_counter()
    assert start - before >= _PING_SLEEP_SECONDS
    assert after - start < _PING_SLEEP_SECONDS
