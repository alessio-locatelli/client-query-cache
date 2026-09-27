from __future__ import annotations

import json
import stat
import sys
from typing import TYPE_CHECKING

import pytest

from tests.benchmark.real_server import atlas_bandwidth
from tests.benchmark.real_server.atlas_bandwidth import (
    ATLAS_PROJECT_ID_ENV_VAR,
    BandwidthEvidence,
    collect_bandwidth_evidence,
    requested_metric_types,
    resolve_atlas_project_id,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_PROJECT_ID = "1234567890abcdef12345678"
_HOST_ID = "atlas-example-shard-00-01.example.mongodb.net:27017"

_SECONDARY_HOST_ID = "atlas-example-shard-00-00.example.mongodb.net:27017"

_PROCESSES_LIST_RESPONSE = json.dumps(
    {
        "results": [
            {"id": _SECONDARY_HOST_ID, "typeName": "REPLICA_SECONDARY"},
            {"id": _HOST_ID, "typeName": "REPLICA_PRIMARY"},
        ]
    }
)

_PROCESSES_LIST_RESPONSE_NO_PRIMARY = json.dumps(
    {"results": [{"id": "a:27017", "typeName": "REPLICA_SECONDARY"}]}
)

_METRICS_RESPONSE_WITH_DATA = json.dumps(
    {
        "hostId": _HOST_ID,
        "measurements": [
            {
                "name": "NETWORK_BYTES_IN",
                "dataPoints": [{"timestamp": "2026-09-27T17:32:32Z", "value": 1633.7}],
            },
            {
                "name": "NETWORK_BYTES_OUT",
                "dataPoints": [{"timestamp": "2026-09-27T17:32:32Z", "value": None}],
            },
        ],
    }
)

_METRICS_RESPONSE_ALL_EMPTY = json.dumps(
    {
        "hostId": _HOST_ID,
        "measurements": [
            {"name": "NETWORK_BYTES_IN", "dataPoints": []},
            {"name": "NETWORK_BYTES_OUT", "dataPoints": []},
        ],
    }
)


def _write_fake_atlas(tmp_path: Path, *, dispatch: dict[str, str]) -> None:
    fake_atlas = tmp_path / "atlas"
    branches = "\n".join(
        f"""    if {marker!r} in argv:
        print({response!r})
        raise SystemExit(0)"""
        for marker, response in dispatch.items()
    )
    fake_atlas.write_text(
        f"""#!{sys.executable}
import sys

def main() -> None:
    argv = sys.argv[1:]
{branches}
    raise SystemExit(1)

if __name__ == "__main__":
    main()
"""
    )
    fake_atlas.chmod(fake_atlas.stat().st_mode | stat.S_IEXEC)


@pytest.fixture(autouse=True)
def _clear_atlas_project_id_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ATLAS_PROJECT_ID_ENV_VAR, raising=False)


def test_resolve_atlas_project_id_returns_none_when_unset() -> None:
    assert resolve_atlas_project_id() is None


def test_resolve_atlas_project_id_returns_the_configured_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ATLAS_PROJECT_ID_ENV_VAR, _PROJECT_ID)

    assert resolve_atlas_project_id() == _PROJECT_ID


def test_requested_metric_types_never_includes_process_cpu_metrics() -> None:
    assert not any("CPU" in metric_type for metric_type in requested_metric_types())


@pytest.mark.parametrize(
    "dispatch",
    [
        pytest.param(None, id="atlas_cli_is_absent"),
        pytest.param({}, id="atlas_cli_fails"),
        pytest.param(
            {"list": _PROCESSES_LIST_RESPONSE_NO_PRIMARY},
            id="no_primary_process_is_found",
        ),
        pytest.param(
            {"list": _PROCESSES_LIST_RESPONSE, "metrics": _METRICS_RESPONSE_ALL_EMPTY},
            id="all_data_points_are_empty",
        ),
    ],
)
def test_collect_bandwidth_evidence_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dispatch: dict[str, str] | None
) -> None:
    if dispatch is not None:
        _write_fake_atlas(tmp_path, dispatch=dispatch)
    monkeypatch.setenv("PATH", str(tmp_path))

    assert collect_bandwidth_evidence(_PROJECT_ID) is None


@pytest.mark.parametrize(
    "dispatch",
    [
        pytest.param({}, id="atlas_cli_fails"),
        pytest.param(
            {"list": _PROCESSES_LIST_RESPONSE_NO_PRIMARY},
            id="no_primary_process_is_found",
        ),
    ],
)
def test_collect_bandwidth_evidence_never_logs_the_project_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    dispatch: dict[str, str],
) -> None:
    _write_fake_atlas(tmp_path, dispatch=dispatch)
    monkeypatch.setenv("PATH", str(tmp_path))

    with caplog.at_level("WARNING"):
        collect_bandwidth_evidence(_PROJECT_ID)

    assert _PROJECT_ID not in caplog.text


def test_collect_bandwidth_evidence_returns_none_when_atlas_cli_times_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_atlas = tmp_path / "atlas"
    fake_atlas.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(5)\n")
    fake_atlas.chmod(fake_atlas.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(atlas_bandwidth, "_ATLAS_TIMEOUT_SECONDS", 0.05)

    assert collect_bandwidth_evidence(_PROJECT_ID) is None


def test_collect_bandwidth_evidence_returns_evidence_when_data_is_available(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_fake_atlas(
        tmp_path,
        dispatch={
            "list": _PROCESSES_LIST_RESPONSE,
            "metrics": _METRICS_RESPONSE_WITH_DATA,
        },
    )
    monkeypatch.setenv("PATH", str(tmp_path))

    evidence = collect_bandwidth_evidence(_PROJECT_ID)

    assert evidence == BandwidthEvidence(
        host_id=_HOST_ID, measurements={"NETWORK_BYTES_IN": (1633.7,)}
    )
