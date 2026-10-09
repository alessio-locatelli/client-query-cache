from __future__ import annotations

import json
import stat
import sys
import time
from typing import TYPE_CHECKING

import dns.resolver
import pytest

from client_query_cache._types import NonNegativeInt
from tests.benchmark.real_server import atlas_bandwidth
from tests.benchmark.real_server.atlas_bandwidth import (
    ATLAS_PROJECT_ID_ENV_VAR,
    BandwidthEvidence,
    collect_bandwidth_evidence,
    requested_metric_types,
    resolve_atlas_project_id,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

pytestmark = pytest.mark.unit

_PROJECT_ID = "1234567890abcdef12345678"
_MONGODB_URI = (
    "mongodb+srv://user:pass@cluster0.example.mongodb.net/"  # pragma: allowlist secret
)
_MEMBER_ALIAS = "ac-example-shard-00-01.example.mongodb.net"
_MEMBER_PORT = 27017
_HOST_ID = "atlas-example-shard-00-01.example.mongodb.net:27017"

_SECONDARY_HOST_ID = "atlas-example-shard-00-00.example.mongodb.net:27017"
_UNRELATED_ALIAS = "ac-other-shard-00-01.other.mongodb.net"

_PROCESSES_LIST_RESPONSE = json.dumps(
    {
        "results": [
            {
                "id": _SECONDARY_HOST_ID,
                "typeName": "REPLICA_SECONDARY",
                "userAlias": "ac-example-shard-00-00.example.mongodb.net",
                "port": _MEMBER_PORT,
            },
            {
                "id": _HOST_ID,
                "typeName": "REPLICA_PRIMARY",
                "userAlias": _MEMBER_ALIAS,
                "port": _MEMBER_PORT,
            },
        ]
    }
)

_PROCESSES_LIST_RESPONSE_UNRELATED_PRIMARY = json.dumps(
    {
        "results": [
            {
                "id": "atlas-other-shard-00-01.other.mongodb.net:27017",
                "typeName": "REPLICA_PRIMARY",
                "userAlias": _UNRELATED_ALIAS,
                "port": _MEMBER_PORT,
            },
            {
                "id": _HOST_ID,
                "typeName": "REPLICA_SECONDARY",
                "userAlias": _MEMBER_ALIAS,
                "port": _MEMBER_PORT,
            },
        ]
    }
)

_PROCESSES_LIST_RESPONSE_NO_PRIMARY = json.dumps(
    {
        "results": [
            {
                "id": _SECONDARY_HOST_ID,
                "typeName": "REPLICA_SECONDARY",
                "userAlias": _MEMBER_ALIAS,
                "port": _MEMBER_PORT,
            }
        ]
    }
)

_PROCESSES_LIST_RESPONSE_HOSTNAME_FALLBACK = json.dumps(
    {
        "results": [
            {
                "id": "atlas-portless.example.mongodb.net:27017",
                "typeName": "REPLICA_PRIMARY",
            },
            {
                "id": _HOST_ID,
                "typeName": "REPLICA_PRIMARY",
                "hostname": _MEMBER_ALIAS,
                "port": _MEMBER_PORT,
            },
        ]
    }
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


class _FakeSrvRecord:
    __slots__ = ("port", "target")

    def __init__(self, target: str, port: NonNegativeInt) -> None:
        self.target = f"{target}."
        self.port = port


def _fake_resolve(records: Sequence[_FakeSrvRecord]) -> object:
    def resolve(qname: str, rdtype: str) -> Sequence[_FakeSrvRecord]:
        assert rdtype == "SRV"
        assert qname == "_mongodb._tcp.cluster0.example.mongodb.net"
        return records

    return resolve


def _mock_srv_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        dns.resolver,
        "resolve",
        _fake_resolve([_FakeSrvRecord(_MEMBER_ALIAS, _MEMBER_PORT)]),
    )


def _write_fake_atlas(tmp_path: Path, *, dispatch: dict[str, str]) -> None:
    fake_atlas = tmp_path / "atlas"
    branches = "\n".join(
        f"""    if argv[:1] == [{marker!r}]:
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


def test_collect_bandwidth_evidence_returns_none_when_the_uri_is_not_srv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))

    uri = (
        "mongodb://user:pass@cluster0.example.mongodb.net/"  # pragma: allowlist secret
    )
    assert collect_bandwidth_evidence(_PROJECT_ID, uri) is None


def test_collect_bandwidth_evidence_returns_none_when_the_uri_has_no_hostname(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))

    assert collect_bandwidth_evidence(_PROJECT_ID, "mongodb+srv://") is None


def test_collect_bandwidth_evidence_returns_none_when_srv_resolution_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))

    def _raise_nxdomain(*_args: object) -> Sequence[_FakeSrvRecord]:
        raise dns.resolver.NXDOMAIN

    monkeypatch.setattr(dns.resolver, "resolve", _raise_nxdomain)

    assert collect_bandwidth_evidence(_PROJECT_ID, _MONGODB_URI) is None


@pytest.mark.parametrize(
    "dispatch",
    [
        pytest.param({}, id="atlas_cli_fails"),
        pytest.param({"processes": "not json"}, id="atlas_cli_prints_malformed_json"),
        pytest.param(
            {"processes": _PROCESSES_LIST_RESPONSE_NO_PRIMARY},
            id="no_primary_process_is_found",
        ),
        pytest.param(
            {"processes": _PROCESSES_LIST_RESPONSE_UNRELATED_PRIMARY},
            id="only_an_unrelated_primary_is_found",
        ),
        pytest.param(
            {
                "processes": _PROCESSES_LIST_RESPONSE,
                "metrics": _METRICS_RESPONSE_ALL_EMPTY,
            },
            id="all_data_points_are_empty",
        ),
    ],
)
def test_collect_bandwidth_evidence_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dispatch: dict[str, str]
) -> None:
    _mock_srv_resolution(monkeypatch)
    _write_fake_atlas(tmp_path, dispatch=dispatch)
    monkeypatch.setenv("PATH", str(tmp_path))

    assert collect_bandwidth_evidence(_PROJECT_ID, _MONGODB_URI) is None


def test_collect_bandwidth_evidence_returns_none_when_atlas_cli_cannot_be_executed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _mock_srv_resolution(monkeypatch)
    fake_atlas = tmp_path / "atlas"
    fake_atlas.write_text("#!/nonexistent/interpreter\n")
    fake_atlas.chmod(fake_atlas.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(tmp_path))

    assert collect_bandwidth_evidence(_PROJECT_ID, _MONGODB_URI) is None


def test_collect_bandwidth_evidence_returns_none_when_atlas_cli_is_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _mock_srv_resolution(monkeypatch)
    monkeypatch.setenv("PATH", str(tmp_path))

    assert collect_bandwidth_evidence(_PROJECT_ID, _MONGODB_URI) is None


@pytest.mark.parametrize(
    "dispatch",
    [
        pytest.param({}, id="atlas_cli_fails"),
        pytest.param(
            {"processes": _PROCESSES_LIST_RESPONSE_NO_PRIMARY},
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
    _mock_srv_resolution(monkeypatch)
    _write_fake_atlas(tmp_path, dispatch=dispatch)
    monkeypatch.setenv("PATH", str(tmp_path))

    with caplog.at_level("WARNING"):
        collect_bandwidth_evidence(_PROJECT_ID, _MONGODB_URI)

    assert _PROJECT_ID not in caplog.text


def test_collect_bandwidth_evidence_returns_none_when_the_budget_is_exhausted_early(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _mock_srv_resolution(monkeypatch)
    monkeypatch.setenv("PATH", str(tmp_path))
    monotonic_values = iter([0.0, 100.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(monotonic_values))

    def _fail_if_called(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("atlas CLI must not run once the budget is exhausted")

    monkeypatch.setattr(atlas_bandwidth, "_primary_process_host_id", _fail_if_called)

    assert collect_bandwidth_evidence(_PROJECT_ID, _MONGODB_URI) is None


def test_collect_bandwidth_evidence_returns_none_when_the_budget_runs_out_between_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _mock_srv_resolution(monkeypatch)
    monkeypatch.setenv("PATH", str(tmp_path))
    monotonic_values = iter([0.0, 0.0, 100.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(
        atlas_bandwidth, "_primary_process_host_id", lambda *_args, **_kwargs: _HOST_ID
    )

    def _fail_if_called(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("metrics must not be fetched once the budget is exhausted")

    monkeypatch.setattr(atlas_bandwidth, "_run_atlas", _fail_if_called)

    assert collect_bandwidth_evidence(_PROJECT_ID, _MONGODB_URI) is None


def test_collect_bandwidth_evidence_returns_none_when_atlas_cli_times_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _mock_srv_resolution(monkeypatch)
    fake_atlas = tmp_path / "atlas"
    fake_atlas.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(5)\n")
    fake_atlas.chmod(fake_atlas.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(atlas_bandwidth, "_ATLAS_TIMEOUT_SECONDS", 0.05)

    assert collect_bandwidth_evidence(_PROJECT_ID, _MONGODB_URI) is None


def test_collect_bandwidth_evidence_returns_evidence_when_data_is_available(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _mock_srv_resolution(monkeypatch)
    _write_fake_atlas(
        tmp_path,
        dispatch={
            "processes": _PROCESSES_LIST_RESPONSE,
            "metrics": _METRICS_RESPONSE_WITH_DATA,
        },
    )
    monkeypatch.setenv("PATH", str(tmp_path))

    evidence = collect_bandwidth_evidence(_PROJECT_ID, _MONGODB_URI)

    assert evidence == BandwidthEvidence(
        host_id=_HOST_ID, measurements={"NETWORK_BYTES_IN": (1633.7,)}
    )


def test_collect_bandwidth_evidence_falls_back_to_the_hostname_field(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _mock_srv_resolution(monkeypatch)
    _write_fake_atlas(
        tmp_path,
        dispatch={
            "processes": _PROCESSES_LIST_RESPONSE_HOSTNAME_FALLBACK,
            "metrics": _METRICS_RESPONSE_WITH_DATA,
        },
    )
    monkeypatch.setenv("PATH", str(tmp_path))

    evidence = collect_bandwidth_evidence(_PROJECT_ID, _MONGODB_URI)

    assert evidence == BandwidthEvidence(
        host_id=_HOST_ID, measurements={"NETWORK_BYTES_IN": (1633.7,)}
    )
