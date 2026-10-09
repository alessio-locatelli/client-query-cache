from __future__ import annotations

import json
import shutil
import subprocess
import sys
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock, call

import pytest

from benchmarks.stream_cost import decision_evidence
from benchmarks.stream_cost.calibration import (
    CalibrationPoint,
    CalibrationSeries,
    ClockSample,
    TopologyChangeListener,
)
from benchmarks.stream_cost.consolidated_stream import PairVariant
from benchmarks.stream_cost.oversized_result import (
    OversizedResultSavingsMeasurement,
    OversizedResultWorkloadMeasurement,
)
from benchmarks.stream_cost.pair_runner import PairResult, RunResult
from client_query_cache._types import NonNegativeFloat

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _pair(*, loaded_lag: float) -> PairResult:
    clock_sample = ClockSample(
        wall_t0=1.0,
        wall_t1=1.002,
        monotonic_t0=1.0,
        monotonic_t1=1.002,
        server_time_seconds=1.001,
        election_id="election-1",
    )
    calibration = CalibrationSeries(
        points=(CalibrationPoint(selected=clock_sample, rounds=(clock_sample,)),)
    )

    def make_run(variant: PairVariant, lag: float) -> RunResult:
        return RunResult(
            variant=variant,
            relevant_write_count=40,
            unrelated_write_count_during_window=(
                400 if variant is PairVariant.LOADED else 0
            ),
            raw_lag_windows=((lag,) * 10,) * 4,
            invalidation_apply_readings=(),
        )

    return PairResult(
        control=make_run(PairVariant.CONTROL, 0.01),
        loaded=make_run(PairVariant.LOADED, loaded_lag),
        calibration=calibration,
    )


@pytest.mark.parametrize(
    ("loaded_lags", "healthy", "decision"),
    [
        ((0.02, 0.02, 0.02), True, "keep_shipped_serial_database_router"),
        (
            (0.02, 0.7, 0.02),
            False,
            "open_router_stage_instrumentation_followup",
        ),
    ],
)
def test_consolidated_decision_requires_every_pair_to_pass(
    monkeypatch: pytest.MonkeyPatch,
    loaded_lags: tuple[float, ...],
    healthy: bool,
    decision: str,
) -> None:
    pairs = tuple(_pair(loaded_lag=lag) for lag in loaded_lags)
    monkeypatch.setattr(
        decision_evidence,
        "run_consolidated_stream_pairs",
        lambda *_args, **_kwargs: pairs,
    )
    registration = json.loads(decision_evidence._PREREGISTRATION.read_text())
    evidence = decision_evidence._consolidated_evidence(
        MagicMock(), TopologyChangeListener(), registration["consolidated_stream"]
    )
    assert evidence["healthy"] is healthy
    assert evidence["decision"] == decision
    assert [
        pair["healthy"] for pair in cast("list[dict[str, object]]", evidence["pairs"])
    ] == [lag < 0.5 for lag in loaded_lags]


@pytest.mark.parametrize(
    ("full_cost", "decision"),
    [
        (0.002, "leave_full_materialization_as_cost_benefit_judgment"),
        (0.01, "open_incremental_admission_prototype_followup"),
    ],
)
def test_oversized_decision_uses_encoder_savings_only(
    monkeypatch: pytest.MonkeyPatch, full_cost: NonNegativeFloat, decision: str
) -> None:
    registration = json.loads(decision_evidence._PREREGISTRATION.read_text())
    config = registration["oversized_result"]
    manager = MagicMock()
    manager.__enter__.return_value = manager
    manager.cache_core.snapshot = MagicMock(
        side_effect=[
            SimpleNamespace(oversized_bypasses=0),
            SimpleNamespace(oversized_bypasses=1),
        ]
    )
    monkeypatch.setattr(
        decision_evidence, "CacheManager", lambda *_args, **_kwargs: manager
    )
    savings = OversizedResultSavingsMeasurement(
        prefix_length=16,
        prefix_costs_seconds=(0.001,) * 15,
        full_costs_seconds=(full_cost,) * 15,
        acceptable_savings_threshold_seconds=config[
            "acceptable_savings_threshold_seconds"
        ],
    )
    monkeypatch.setattr(
        decision_evidence,
        "measure_oversized_result_workload",
        lambda *_args, **_kwargs: OversizedResultWorkloadMeasurement(
            end_to_end_cost_seconds=1.0, savings=savings
        ),
    )
    evidence = decision_evidence._oversized_evidence(MagicMock(), config)
    assert evidence["decision"] == decision
    assert evidence["encoder_savings_seconds"] == pytest.approx(full_cost - 0.001)
    assert evidence["end_to_end_cost_seconds"] == pytest.approx(1.0)


@pytest.mark.parametrize("git_available", [True, False])
def test_run_decision_evidence_records_provenance_and_closes_client(
    monkeypatch: pytest.MonkeyPatch, git_available: bool
) -> None:
    replica_set = MagicMock()
    replica_set.__enter__.return_value = replica_set
    replica_set.uri = "mongodb://127.0.0.1:27017"
    replica_set.container_cpu_usage_seconds = MagicMock(side_effect=[10.0, 12.0])
    client = MagicMock()
    client.server_info.return_value = {"version": "8.0.4"}
    monkeypatch.setattr(
        decision_evidence, "IsolatedReplicaSet", lambda _limits: replica_set
    )
    monkeypatch.setattr(
        decision_evidence, "build_dedicated_client", lambda *_args, **_kwargs: client
    )
    monkeypatch.setattr(
        decision_evidence,
        "_consolidated_evidence",
        lambda *_args, **_kwargs: {"healthy": True},
    )
    monkeypatch.setattr(
        decision_evidence,
        "_oversized_evidence",
        lambda *_args, **_kwargs: {"decision": "leave_full_materialization"},
    )
    monkeypatch.setattr(
        shutil,
        "which",
        lambda _name: "/usr/bin/git" if git_available else None,
    )
    monkeypatch.setattr(
        subprocess,
        "check_output",
        lambda *_args, **_kwargs: "abc123\n",
    )
    version_lookup = MagicMock(return_value="0.1.0")
    monkeypatch.setattr(decision_evidence, "version", version_lookup)

    if git_available:
        evidence = decision_evidence.run_decision_evidence()
        assert evidence["schema_version"] == 2
        assert evidence["revision"] == "abc123"
        assert evidence["mongodb_container_cpu_seconds"] == pytest.approx(2.0)
        assert evidence["consolidated_stream"] == {"healthy": True}
        versions = cast("dict[str, str]", evidence["versions"])
        assert versions["client_query_cache"] == "0.1.0"
        assert version_lookup.call_args_list == [
            call("pymongo"),
            call("client-query-cache"),
        ]
    else:
        with pytest.raises(RuntimeError, match="git is required"):
            decision_evidence.run_decision_evidence()
    client.close.assert_called_once_with()


def test_main_writes_decision_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / "nested" / "evidence.json"
    monkeypatch.setattr(sys, "argv", ["decision_evidence", "--output", str(output)])
    monkeypatch.setattr(
        decision_evidence, "run_decision_evidence", lambda: {"schema_version": 2}
    )
    decision_evidence.main()
    assert json.loads(output.read_text()) == {"schema_version": 2}
