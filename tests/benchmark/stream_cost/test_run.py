from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from benchmarks.stream_cost.run import _revision, _sample_variant, run_standard_matrix
from benchmarks.stream_cost.topology import ResourceLimits
from benchmarks.stream_cost.workload import STANDARD_WORKLOAD_VARIANTS

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def test_revision_requires_git() -> None:
    with (
        patch("benchmarks.stream_cost.run.shutil.which", return_value=None),
        pytest.raises(RuntimeError, match="git is required"),
    ):
        _revision()


def test_revision_uses_a_unique_git_abbreviation() -> None:
    revision = _revision()

    assert len(revision) >= 7
    assert all(character in "0123456789abcdef" for character in revision)


@pytest.mark.parametrize("fail_client_creation", [False, True])
def test_controlled_run_closes_resources_on_failure(
    tmp_path: Path, *, fail_client_creation: bool
) -> None:
    replica_set = MagicMock()
    replica_set.__enter__.configure_mock(return_value=replica_set)
    replica_set.configure_mock(uri="mongodb://127.0.0.1:27017/?directConnection=true")
    client = MagicMock()
    client_factory = MagicMock(
        side_effect=RuntimeError("client startup failed")
        if fail_client_creation
        else None,
        return_value=client,
    )
    with (
        patch(
            "benchmarks.stream_cost.run.IsolatedReplicaSet", return_value=replica_set
        ),
        patch("benchmarks.stream_cost.run.build_dedicated_client", client_factory),
        patch(
            "benchmarks.stream_cost.run._run_matrix_with_client",
            side_effect=RuntimeError("run failed"),
        ),
        pytest.raises(RuntimeError),
    ):
        run_standard_matrix(tmp_path, limits=ResourceLimits(cpus=1.0, memory="1g"))

    replica_set.__exit__.assert_called_once()
    if not fail_client_creation:
        client.close.assert_called_once()


def test_controlled_run_fails_if_stream_delivery_does_not_settle() -> None:
    manager = MagicMock()
    manager.cache_core.stream_cost_snapshot.return_value = SimpleNamespace(
        invalidations=0
    )
    outcome = SimpleNamespace(writes_issued=1)
    with (
        patch("benchmarks.stream_cost.run.run_workload_variant", return_value=outcome),
        patch("benchmarks.stream_cost.run.time.monotonic", side_effect=[0.0, 16.0]),
        pytest.raises(RuntimeError, match="stream invalidations did not settle"),
    ):
        _sample_variant(
            manager,
            MagicMock(),
            MagicMock(),
            STANDARD_WORKLOAD_VARIANTS[3],
            MagicMock(),
            database_name="measured",
        )
