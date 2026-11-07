from __future__ import annotations

from functools import partial
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from client_query_cache._types import (
    ExclusiveProbability,
    NonEmptyStr,
    NonNegativeFloat,
    NonNegativeInt,
)
from scripts import pgo_training
from scripts.pgo_training import (
    CLEANUP,
    CORE_POLICY_INDEPENDENT,
    CORE_TELEMETRY_POLICY,
    WORKLOADS,
    new_core,
    train,
    verified,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from client_query_cache._shared_index import LocalCacheCore
    from scripts.pgo_training import Workload

pytestmark = pytest.mark.unit


@pytest.fixture
def workload(request: pytest.FixtureRequest) -> Iterator[Workload]:
    name, enabled = request.param
    with CORE_TELEMETRY_POLICY.set(enabled), CLEANUP:
        yield WORKLOADS[name]()


@pytest.fixture
def enabled_training_core() -> Iterator[LocalCacheCore]:
    with CORE_TELEMETRY_POLICY.set(True):
        core = new_core()
    yield core
    core.close()


@pytest.mark.parametrize(
    "workload",
    [
        pytest.param(
            (name, enabled), id=f"{name}-{'enabled' if enabled else 'disabled'}"
        )
        for name in sorted(WORKLOADS)
        for enabled in ((False,) if name in CORE_POLICY_INDEPENDENT else (False, True))
    ],
    indirect=True,
)
def test_workload_runs_a_pass_over_its_declared_operations(
    workload: Workload,
) -> None:
    run, operations = workload
    run()
    assert operations > 0


@pytest.fixture
def training_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[tuple[NonEmptyStr, bool], NonNegativeInt]:
    elapsed: list[NonNegativeFloat] = [0.0]
    passes: dict[tuple[NonEmptyStr, bool], NonNegativeInt] = {}

    def factory(name: NonEmptyStr) -> Workload:
        policy = CORE_TELEMETRY_POLICY.get()
        key = (name, policy)
        passes[key] = 0

        def run() -> None:
            passes[key] += 1
            elapsed[0] += 1.0

        return run, 1

    for name in ("identity_hit_small", "limited_namespace_pressure", "echo_roundtrip"):
        monkeypatch.setitem(WORKLOADS, name, partial(factory, name))
    monkeypatch.setattr(
        pgo_training, "time", SimpleNamespace(monotonic=lambda: elapsed[0])
    )
    return passes


@pytest.mark.parametrize(
    ("disabled_share", "core_passes", "limited_passes"),
    [(0.5, (50, 50), (10, 10)), (0.8, (80, 20), (16, 4))],
    ids=["balanced", "default-priority"],
)
def test_training_schedules_both_core_policies_and_preserves_allocations(
    training_passes: dict[tuple[NonEmptyStr, bool], NonNegativeInt],
    disabled_share: ExclusiveProbability,
    core_passes: tuple[NonNegativeInt, NonNegativeInt],
    limited_passes: tuple[NonNegativeInt, NonNegativeInt],
) -> None:
    train(
        ["identity_hit_small", "limited_namespace_pressure", "echo_roundtrip"],
        seconds=100,
        disabled_share=disabled_share,
    )
    # Each scheduled workload also runs one untimed warmup pass.
    assert training_passes == {
        ("identity_hit_small", False): core_passes[0] + 1,
        ("identity_hit_small", True): core_passes[1] + 1,
        ("limited_namespace_pressure", False): limited_passes[0] + 1,
        ("limited_namespace_pressure", True): limited_passes[1] + 1,
        ("echo_roundtrip", False): 101,
    }
    assert CORE_TELEMETRY_POLICY.get() is False


@pytest.mark.parametrize(("hits", "misses"), [(1, 0), (0, 1)])
def test_verification_rejects_a_pass_without_the_expected_cache_statistics(
    hits: NonNegativeInt, misses: NonNegativeInt, enabled_training_core: LocalCacheCore
) -> None:
    with pytest.raises(SystemExit, match="expected"):
        verified(enabled_training_core, lambda: None, hits=hits, misses=misses)


@pytest.mark.parametrize("disabled_share", [0.0, 1.0, float("nan")])
def test_training_rejects_a_share_that_omits_a_policy(disabled_share: float) -> None:
    with pytest.raises(SystemExit, match="disabled share"):
        train([], seconds=0, disabled_share=disabled_share)
