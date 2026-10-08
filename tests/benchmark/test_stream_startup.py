from __future__ import annotations

import json
import pstats
from pathlib import Path

import pytest

from benchmarks import stream_startup
from client_query_cache._core import stream_activation

pytestmark = pytest.mark.unit


@pytest.fixture
def small_workload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stream_startup, "ACTIVATIONS", 20)
    monkeypatch.setattr(stream_startup, "MEASURED_BATCHES", 2)
    monkeypatch.setattr(stream_activation, "monotonic", lambda: 10.0)


@pytest.fixture(params=[False, True], ids=["timing", "profile"])
def profile_arguments(request: pytest.FixtureRequest, tmp_path: Path) -> list[str]:
    return ["--profile", str(tmp_path / "healthy.prof")] if request.param else []


@pytest.mark.usefixtures("small_workload")
@pytest.mark.parametrize("mode", ["synchronous", "asynchronous"])
def test_harness_measures_coordination_and_writes_a_healthy_profile(
    mode: str,
    profile_arguments: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    stream_startup.main([mode, *profile_arguments])
    measurement = stream_startup.Measurement(**json.loads(capsys.readouterr().out))
    assert measurement.mode == mode
    assert Path(measurement.source).is_relative_to(Path.cwd() / "src")
    assert measurement.healthy_seconds > 0
    assert measurement.failed_seconds > 0
    assert measurement.failure_attempts == measurement.failure_warnings == 1
    assert measurement.b_independent
    assert measurement.b_seconds > 0
    if profile_arguments:
        stats = pstats.Stats(profile_arguments[1])
        activation = stats.get_stats_profile().func_profiles["activate_database"]
        assert int(activation.ncalls) == stream_startup.ACTIVATIONS
