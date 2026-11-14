from __future__ import annotations

from types import ModuleType
from typing import TYPE_CHECKING

import pytest

from research.native_build_profile.compare import ROOT, child_environment
from research.native_build_profile.limits import CONFIGS, WORKLOADS, measure_once
from research.native_build_profile.measure import accept_previous_budget_keyword
from scripts.pgo_training import CLEANUP

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "profile", [None, "training-%p.profraw"], ids=["timing", "pgo"]
)
def test_comparison_children_use_only_the_registered_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, profile: str | None
) -> None:
    for name in ("PYTHONMALLOC", "MALLOC_CONF", "MALLOC_ARENA_MAX", "LD_PRELOAD"):
        monkeypatch.setenv(name, "parent-only")
    monkeypatch.delenv("LLVM_PROFILE_FILE", raising=False)
    expected = {
        "PYTHONPATH": f"{tmp_path}:{ROOT}",
        "PYTHONHASHSEED": "0",
        "PATH": "/usr/bin:/bin",
    }
    if profile is not None:
        monkeypatch.setenv("LLVM_PROFILE_FILE", profile)
        expected["LLVM_PROFILE_FILE"] = profile

    assert child_environment(tmp_path) == expected


def current(*, budget_bytes: int, max_entry_bytes: int) -> tuple[str, int, int]:
    return "current", budget_bytes, max_entry_bytes


def previous(*, shared_budget_bytes: int, max_entry_bytes: int) -> tuple[str, int, int]:
    return "previous", shared_budget_bytes, max_entry_bytes


@pytest.mark.parametrize("config", [current, previous], ids=["current", "previous"])
def test_the_training_workloads_construct_the_budget_keyword_the_build_declares(
    config: Callable[..., tuple[str, int, int]],
) -> None:
    training = ModuleType("training")
    vars(training)["CacheCoreConfig"] = current
    accept_previous_budget_keyword(training, config)
    configure = vars(training)["CacheCoreConfig"]
    assert configure(budget_bytes=8, max_entry_bytes=2) == (config.__name__, 8, 2)


@pytest.fixture
def cleanup() -> Iterator[None]:
    with CLEANUP:
        yield


@pytest.mark.usefixtures("cleanup")
@pytest.mark.parametrize("config", sorted(CONFIGS))
@pytest.mark.parametrize("workload", sorted(WORKLOADS))
def test_every_limit_workload_completes_under_every_configuration(
    workload: str, config: str
) -> None:
    assert measure_once(WORKLOADS[workload], CONFIGS[config]) > 0
