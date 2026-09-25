from __future__ import annotations

import ast
import inspect
from typing import TYPE_CHECKING

import pytest

from benchmarks.stream_cost import guard_workload

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
