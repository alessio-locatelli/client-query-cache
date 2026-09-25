from __future__ import annotations

import ast
import inspect
import json
import sys
from typing import TYPE_CHECKING

import pytest

from benchmarks.stream_cost import guard_workload
from benchmarks.stream_cost.guard_workload import run_case

if TYPE_CHECKING:
    from types import ModuleType

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
    assert "mongo_client_cache._core.stream_events" in imported


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
