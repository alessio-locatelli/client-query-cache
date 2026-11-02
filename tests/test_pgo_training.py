from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from scripts.pgo_training import CLEANUP, WORKLOADS, new_core, train, verified

if TYPE_CHECKING:
    from collections.abc import Iterator

    from scripts.pgo_training import Workload

pytestmark = pytest.mark.unit


@pytest.fixture
def workload(request: pytest.FixtureRequest) -> Iterator[Workload]:
    with CLEANUP:
        yield WORKLOADS[request.param]()


@pytest.mark.parametrize("workload", sorted(WORKLOADS), indirect=True)
def test_workload_runs_a_pass_over_its_declared_operations(
    workload: Workload,
) -> None:
    run, operations = workload
    run()
    assert operations > 0


def test_training_runs_every_selected_workload_for_the_requested_time() -> None:
    train(["identity_hit_small", "echo_roundtrip"], seconds=0.01)


@pytest.mark.parametrize(("hits", "misses"), [(1, 0), (0, 1)])
def test_verification_rejects_a_pass_without_the_expected_cache_statistics(
    hits: int, misses: int
) -> None:
    with pytest.raises(SystemExit, match="expected"):
        verified(new_core(), lambda: None, hits=hits, misses=misses)
