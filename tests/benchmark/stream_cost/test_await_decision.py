from __future__ import annotations

import hashlib
import json
import shutil
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pymongo.errors import ConnectionFailure

from benchmarks.stream_cost import await_report, await_run
from benchmarks.stream_cost.await_configuration import (
    expand_await_configuration,
    load_await_configuration,
)
from benchmarks.stream_cost.await_decision import evaluate_await_decision
from benchmarks.stream_cost.await_model import AwaitWindow
from benchmarks.stream_cost.await_statistics import exact_block_bootstrap, holm_adjusted
from benchmarks.stream_cost.errors import (
    BenchmarkConfigurationError,
    BenchmarkSetupError,
)

if TYPE_CHECKING:
    from benchmarks.stream_cost.await_model import AwaitConfiguration

pytestmark = pytest.mark.unit

_CONFIGURATION_PATH = Path("reports/stream-cost/await-v1/config.v1.json")
_BASELINE_SERVER_CPU = 12.0
_BASELINE_BYTES = 100_000
_ACTIVE_CPU = 1.0
_LAG_SECONDS = 0.01
_SHUTDOWN_SECONDS = 0.1


@pytest.fixture
def configuration() -> AwaitConfiguration:
    return load_await_configuration(_CONFIGURATION_PATH.read_bytes())


@pytest.fixture
def windows(configuration: AwaitConfiguration) -> tuple[AwaitWindow, ...]:
    samples = []
    for block, candidates in enumerate(configuration["block_orders"]):
        for candidate in candidates:
            saving = 1 if candidate == 1000 else 0.5
            for model in configuration["model_orders"][block]:
                for workload in ("idle", "paced", "burst", "shutdown"):
                    schedule = (
                        tuple(configuration["write_offsets_seconds"][workload])
                        if workload in {"paced", "burst"}
                        else ()
                    )
                    elapsed = (
                        configuration["idle_minimum_seconds"]
                        if workload == "idle"
                        else configuration["active_window_seconds"]
                    )
                    commands = 2 if workload == "idle" else 200
                    shutdown = (
                        (_SHUTDOWN_SECONDS,)
                        * len(configuration["shutdown_trial_offsets_seconds"])
                        if workload == "shutdown"
                        else ()
                    )
                    if shutdown:
                        commands = len(shutdown)
                    samples.append(
                        AwaitWindow(
                            block=block,
                            candidate_ms=candidate,
                            model=model,
                            workload=workload,
                            elapsed_seconds=sum(shutdown) if shutdown else elapsed,
                            server_cpu_seconds=None
                            if shutdown
                            else (
                                _BASELINE_SERVER_CPU * saving
                                if workload == "idle"
                                else _ACTIVE_CPU
                            ),
                            client_cpu_seconds=None if shutdown else _ACTIVE_CPU,
                            bytes_sent=None
                            if shutdown
                            else int(_BASELINE_BYTES * saving),
                            bytes_received=None
                            if shutdown
                            else int(_BASELINE_BYTES * saving),
                            getmore_started=0 if shutdown else commands,
                            getmore_inflight_at_start=commands if shutdown else 0,
                            getmore_completed=commands,
                            requested_max_time_ms=(candidate,) * commands,
                            command_failures=0,
                            manager_iteration_calls=0
                            if workload == "idle"
                            else len(schedule),
                            issue_offsets_seconds=schedule,
                            lag_seconds=(_LAG_SECONDS,) * len(schedule),
                            shutdown_seconds=shutdown,
                            shutdown_start_offsets_seconds=tuple(
                                configuration["shutdown_trial_offsets_seconds"]
                            )
                            if shutdown
                            else (),
                            shutdown_inflight=(True,) * len(shutdown),
                            invalidations=len(schedule),
                            healthy=True,
                            failure=None,
                        )
                    )
    return tuple(samples)


@pytest.fixture
def report(
    windows: tuple[AwaitWindow, ...],
    configuration: AwaitConfiguration,
) -> dict[str, object]:
    digest = await_report.configuration_hash(_CONFIGURATION_PATH.read_bytes())
    return {
        "schema_version": 1,
        "configuration_sha256": digest,
        "revision": "synthetic-test-fixture",
        "environment": dict.fromkeys(
            ("python", "pymongo", "client_query_cache", "mongodb", "platform"),
            "synthetic-test-fixture",
        ),
        "topology": configuration["topology"].copy(),
        "command_count_source": "pymongo_command_listener",
        "scope": "tested_single_member_replica_set_only",
        "client_options": configuration["client_options"],
        "samples": [asdict(window) for window in windows],
        "failures": [],
    }


def test_compact_configuration_expands_to_the_frozen_original_semantics(
    configuration: AwaitConfiguration,
) -> None:
    canonical = json.dumps(configuration, sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(canonical.encode()).hexdigest() == (
        # pragma: allowlist nextline secret
        "792be6aeb1e08383fae2cde4f3b749c53e4effa3302461da8f89a3acf3aca661"
    )
    assert expand_await_configuration(configuration) == configuration


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b'{"comparison_plan": {}}', id="incomplete-compact-definition"),
        pytest.param(b"1", id="non-object-definition"),
        pytest.param(b"not json", id="malformed-json"),
    ],
)
def test_configuration_loader_rejects_an_invalid_definition(content: bytes) -> None:
    with pytest.raises(BenchmarkConfigurationError, match="invalid await-time"):
        load_await_configuration(content)


def test_report_retains_matched_complete_measurements(
    report: dict[str, object],
    configuration: AwaitConfiguration,
    windows: tuple[AwaitWindow, ...],
) -> None:
    assert (
        await_report.validate_await_report(
            report, configuration, await_report.CONFIGURATION_SHA256
        )
        == windows
    )


def test_accepts_shutdown_cancellation_without_a_completion_notification(
    report: dict[str, object], configuration: AwaitConfiguration
) -> None:
    samples = cast("list[dict[str, object]]", report["samples"])
    shutdown = next(sample for sample in samples if sample["workload"] == "shutdown")
    shutdown["getmore_completed"] = 0
    validated = await_report.validate_await_report(
        report, configuration, await_report.CONFIGURATION_SHA256
    )
    assert (
        next(
            sample for sample in validated if sample.workload == "shutdown"
        ).getmore_completed
        == 0
    )


@pytest.mark.parametrize(
    "defect",
    ["missing", "schedule", "events", "topology", "source", "hash"],
    ids=[
        "missing-measurement",
        "unequal-schedule",
        "unequal-events",
        "wrong-topology",
        "iteration-count",
        "altered-hash",
    ],
)
def test_rejects_invalid_measurements(
    report: dict[str, object], configuration: AwaitConfiguration, defect: str
) -> None:
    samples = cast("list[dict[str, object]]", report["samples"])
    if defect == "missing":
        samples[0].pop("server_cpu_seconds")
    elif defect == "schedule":
        samples[1]["issue_offsets_seconds"] = [0] * 200
    elif defect == "events":
        samples[1]["invalidations"] = 199
    elif defect == "topology":
        report["topology"] = {"kind": "sharded_cluster"}
    elif defect == "source":
        report["command_count_source"] = "stream_polls"
    else:
        report["configuration_sha256"] = "changed"
    with pytest.raises(BenchmarkConfigurationError):
        await_report.validate_await_report(
            report, configuration, await_report.CONFIGURATION_SHA256
        )


def test_rejects_altered_configuration_hash(report: dict[str, object]) -> None:
    assert report["configuration_sha256"] == await_report.configuration_hash(
        _CONFIGURATION_PATH.read_bytes()
    )
    with pytest.raises(BenchmarkConfigurationError, match="frozen configuration"):
        await_report.configuration_hash(_CONFIGURATION_PATH.read_bytes() + b" ")


@pytest.mark.parametrize(
    "winner_metric",
    ["tie", "cpu", "bytes", "async-regression", "cpu-before-bytes", "only-one"],
    ids=[
        "shorter-wait",
        "cpu-winner",
        "byte-winner",
        "requires-both-models",
        "cpu-priority",
        "only-eligible",
    ],
)
def test_selects_by_both_models_then_shorter_wait(
    windows: tuple[AwaitWindow, ...],
    configuration: AwaitConfiguration,
    winner_metric: str,
) -> None:
    revised = []
    for window in windows:
        modified = window
        if window.candidate_ms == 10000:
            if window.workload == "idle" and winner_metric in {
                "cpu",
                "cpu-before-bytes",
            }:
                assert window.server_cpu_seconds is not None
                modified = replace(
                    window, server_cpu_seconds=window.server_cpu_seconds * 0.5
                )
            elif window.workload == "idle" and winner_metric in {
                "bytes",
                "async-regression",
            }:
                assert window.bytes_sent is not None
                assert window.bytes_received is not None
                modified = replace(
                    window,
                    bytes_sent=window.bytes_sent // 2,
                    bytes_received=window.bytes_received // 2,
                )
            elif (
                window.workload == "paced"
                and window.model == "async"
                and winner_metric == "async-regression"
            ):
                modified = replace(window, client_cpu_seconds=_ACTIVE_CPU * 2)
        if (
            winner_metric == "cpu-before-bytes"
            and window.candidate_ms == 30000
            and window.workload == "idle"
        ):
            modified = replace(
                window,
                bytes_sent=_BASELINE_BYTES // 8,
                bytes_received=_BASELINE_BYTES // 8,
            )
        if (
            winner_metric == "only-one"
            and window.candidate_ms not in {1000, 10000}
            and window.workload == "idle"
        ):
            modified = replace(window, client_cpu_seconds=_ACTIVE_CPU * 2)
        revised.append(modified)
    decision = evaluate_await_decision(revised, configuration)
    assert decision.selected_ms == (
        10000
        if winner_metric in {"cpu", "bytes", "cpu-before-bytes", "only-one"}
        else 5000
    )
    assert len(decision.comparisons) == 128


@pytest.mark.parametrize(
    "defect",
    ["client-cpu", "denominator", "shutdown"],
    ids=["client-regression", "unresolved-denominator", "shutdown-limit"],
)
def test_ineligible_candidates_retain_baseline(
    windows: tuple[AwaitWindow, ...], configuration: AwaitConfiguration, defect: str
) -> None:
    revised = []
    for window in windows:
        modified = window
        if (
            defect == "client-cpu"
            and window.workload == "idle"
            and window.candidate_ms != 1000
        ):
            modified = replace(window, client_cpu_seconds=_ACTIVE_CPU * 2)
        elif (
            defect == "denominator"
            and window.workload == "idle"
            and window.candidate_ms == 1000
        ):
            modified = replace(window, client_cpu_seconds=0)
        elif defect == "shutdown" and window.workload == "shutdown":
            modified = replace(
                window, shutdown_seconds=(3.0,) * len(window.shutdown_seconds)
            )
        revised.append(modified)
    decision = evaluate_await_decision(revised, configuration)
    assert decision.selected_ms == 1000
    assert decision.inconclusive
    assert decision.eligible_ms == ()


@given(st.lists(st.floats(min_value=0, max_value=1), min_size=1, max_size=30))
def test_holm_adjustment_preserves_order_and_never_reduces_p_values(
    p_values: list[float],
) -> None:
    adjusted = holm_adjusted(p_values)
    assert all(
        raw <= corrected <= 1 for raw, corrected in zip(p_values, adjusted, strict=True)
    )
    ordered = [
        adjusted[index]
        for index in sorted(range(len(p_values)), key=p_values.__getitem__)
    ]
    assert ordered == sorted(ordered)


def _constant_statistic(_indices: tuple[int, ...]) -> float:
    return 0.5


def test_exact_bootstrap_counts_all_ordered_draws() -> None:
    test = exact_block_bootstrap(_constant_statistic, block_count=6, limit=0.95)
    assert sum(sample.weight for sample in test.centered_samples) == 6**6
    assert test.p_value == pytest.approx(1 / (1 + 6**6))
    assert test.upper_bound(0.05) == pytest.approx(0.5)


def test_rejects_changed_decision_rules_with_unchanged_hash(
    report: dict[str, object], configuration: AwaitConfiguration
) -> None:
    configuration["uncertainty"]["confidence_level"] = 0.5
    with pytest.raises(BenchmarkConfigurationError, match="frozen configuration"):
        await_report.validate_await_report(
            report, configuration, await_report.CONFIGURATION_SHA256
        )


@pytest.mark.parametrize(
    "candidate", [1000, 5000], ids=["failed-baseline", "failed-candidate"]
)
def test_retains_failed_windows_without_treating_them_as_savings(
    report: dict[str, object], configuration: AwaitConfiguration, candidate: int
) -> None:
    samples = cast("list[dict[str, object]]", report["samples"])
    failed = next(sample for sample in samples if sample["candidate_ms"] == candidate)
    samples.remove(failed)
    report["failures"] = [
        {key: failed[key] for key in ("block", "candidate_ms", "model", "workload")}
        | {"error_type": "TimeoutError", "reason": "TimeoutError"}
    ]
    validated = await_report.validate_await_report(
        report, configuration, await_report.CONFIGURATION_SHA256
    )
    decision = evaluate_await_decision(validated, configuration)
    assert decision.selected_ms == (1000 if candidate == 1000 else 10000)
    assert candidate not in decision.eligible_ms
    assert len(decision.comparisons) == 128


def test_candidate_orders_cover_every_position(
    configuration: AwaitConfiguration,
) -> None:
    for position in range(len(configuration["candidates_ms"])):
        candidates = [order[position] for order in configuration["block_orders"]]
        assert set(candidates) == set(configuration["candidates_ms"])
        assert max(candidates.count(candidate) for candidate in candidates) == 2


@pytest.mark.parametrize("unresolved", ["baseline", "candidate"])
def test_unresolved_cpu_ranking_can_still_select_by_bytes(
    windows: tuple[AwaitWindow, ...],
    configuration: AwaitConfiguration,
    unresolved: str,
) -> None:
    samples = tuple(
        replace(
            window,
            server_cpu_seconds=0
            if window.candidate_ms == (1000 if unresolved == "baseline" else 5000)
            else window.server_cpu_seconds,
            bytes_sent=_BASELINE_BYTES // 4
            if window.candidate_ms == 10000
            else window.bytes_sent,
        )
        if window.workload == "idle"
        else window
        for window in windows
    )
    decision = evaluate_await_decision(samples, configuration)
    assert decision.selected_ms == 10000
    assert not decision.inconclusive


def test_validation_cli_reproduces_decision_from_retained_report(
    report: dict[str, object], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "report.json"
    output.write_text(json.dumps(report))
    monkeypatch.setattr(
        sys, "argv", ["await_run", "--output", str(output), "--validate-only"]
    )
    await_run.main()
    decision = json.loads(output.with_suffix(".decision.json").read_bytes())
    assert decision["selected_ms"] == 5000
    assert decision["report_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert decision["configuration_sha256"] == report["configuration_sha256"]


@pytest.mark.parametrize(
    ("failure", "expected_reason"),
    [
        pytest.param(None, None, id="complete"),
        pytest.param(
            BenchmarkSetupError("resource counter unavailable"),
            "resource counter unavailable",
            id="setup-failure",
        ),
        pytest.param(
            ConnectionFailure("private command"),
            "ConnectionFailure",
            id="driver-failure",
        ),
        pytest.param(TimeoutError(), "TimeoutError", id="timeout"),
    ],
)
def test_matrix_retains_complete_report_and_failure_evidence(
    report: dict[str, object],
    windows: tuple[AwaitWindow, ...],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    failure: Exception | None,
    expected_reason: str | None,
) -> None:
    replica = MagicMock()
    replica.uri = "mongodb://localhost:27017"
    topology = MagicMock()
    topology.__enter__.return_value = replica
    client = MagicMock()
    client.__enter__.return_value.server_info.return_value = {"version": "test-server"}
    monkeypatch.setattr(
        await_run, "IsolatedReplicaSet", MagicMock(return_value=topology)
    )
    client_class = MagicMock()
    client_class.__getitem__.return_value.return_value = client
    monkeypatch.setattr(await_run, "MongoClient", client_class)
    regular: list[AwaitWindow | Exception] = [
        window for window in windows if window.workload != "shutdown"
    ]
    if failure is not None:
        regular[0] = failure
    monkeypatch.setattr(await_run, "run_window", AsyncMock(side_effect=regular))
    monkeypatch.setattr(
        await_run,
        "run_bounded_shutdown",
        MagicMock(
            side_effect=[window for window in windows if window.workload == "shutdown"]
        ),
    )
    output = tmp_path / "new-directory" / "report.json"
    monkeypatch.setattr(sys, "argv", ["await_run", "--output", str(output)])
    await_run.main()
    retained = json.loads(output.read_bytes())
    assert retained["configuration_sha256"] == report["configuration_sha256"]
    assert len(retained["samples"]) == len(windows) - (failure is not None)
    assert [item["reason"] for item in retained["failures"]] == (
        [] if expected_reason is None else [expected_reason]
    )
    assert output.with_suffix(".decision.json").exists()
    with pytest.raises(BenchmarkSetupError, match="new output path"):
        await_run.run_matrix(output)


def test_matrix_requires_revision_tool(
    report: dict[str, object], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert report["configuration_sha256"] == await_report.CONFIGURATION_SHA256
    monkeypatch.setattr(shutil, "which", lambda _: None)
    with pytest.raises(BenchmarkSetupError, match="git is required"):
        await_run.run_matrix(tmp_path / "report.json")
