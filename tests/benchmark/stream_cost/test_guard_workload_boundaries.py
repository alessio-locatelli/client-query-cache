from __future__ import annotations

import ast
import inspect
import json
import sys
from dataclasses import make_dataclass
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from pymongo.monitoring import CommandStartedEvent

from benchmarks.stream_cost import guard_workload
from benchmarks.stream_cost.guard_workload import run_case

if TYPE_CHECKING:
    from types import ModuleType

    from faker import Faker

pytestmark = pytest.mark.unit

_EXCLUDED_MODULES = (
    "benchmarks.stream_cost.workload",
    "benchmarks.stream_cost.decision_evidence",
    "benchmarks.stream_cost.pair_runner",
    "benchmarks.stream_cost.topology",
)


def _imported_module_names(module: ModuleType) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return names


def test_guard_workload_does_not_import_controlled_matrix_or_decision_runner() -> None:
    imported = _imported_module_names(guard_workload)
    assert imported.isdisjoint(_EXCLUDED_MODULES)


def test_guard_workload_reuses_shared_generators_and_cache_snapshots() -> None:
    imported = _imported_module_names(guard_workload)
    assert "benchmarks.stream_cost.generators" in imported
    assert "client_query_cache._core.stream_events" in imported


@pytest.mark.parametrize("policy", ["opt-in", "always-on"])
@pytest.mark.parametrize("enabled", [False, True], ids=["default", "enabled"])
def test_guard_enables_diagnostics_for_both_configuration_apis(
    monkeypatch: pytest.MonkeyPatch, policy: str, *, enabled: bool
) -> None:
    if policy == "always-on":
        monkeypatch.setattr(
            guard_workload,
            "CacheCoreConfig",
            make_dataclass("AlwaysOnTelemetryConfig", (), frozen=True, slots=True),
        )

    config = guard_workload._cache_config(enable_telemetry=enabled)

    if policy == "opt-in":
        assert config.enable_telemetry is enabled
    else:
        assert not hasattr(config, "enable_telemetry")


@pytest.mark.parametrize("database", ["guard", "unrelated"])
@pytest.mark.parametrize("command", ["find", "aggregate"])
def test_hit_oracle_counts_only_reads_of_the_guard_database(
    faker: Faker, database: str, command: str
) -> None:
    commands = guard_workload._ReadCommands()

    commands.started(
        CommandStartedEvent(
            {command: "documents"},
            database,
            faker.random_int(),
            (faker.hostname(), faker.port_number()),
            operation_id=faker.random_int(),
        )
    )
    commands.succeeded(Mock())
    commands.failed(Mock())

    assert commands.finds == (command == "find" and database == "guard")


@pytest.mark.parametrize(
    ("case", "profile"),
    [
        ("not_a_case", "small"),
        ("sync_hit", "not_a_profile"),
    ],
)
def test_run_case_rejects_an_unknown_case_or_profile(case: str, profile: str) -> None:
    with pytest.raises(ValueError, match="unknown guard case or document profile"):
        run_case("mongodb://unused", case, profile)


def test_main_prints_the_elapsed_seconds(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        guard_workload,
        "run_case",
        lambda _uri, _case, _profile: 0.042,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "guard_workload",
            "--uri",
            "mongodb://unused",
            "--case",
            "sync_hit",
            "--profile",
            "small",
        ],
    )

    guard_workload.main()

    assert json.loads(capsys.readouterr().out) == {"elapsed_seconds": 0.042}
