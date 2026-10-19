from __future__ import annotations

import socket
from typing import TYPE_CHECKING, ClassVar, Self, cast

import pytest
from docker.errors import DockerException
from pymongo.errors import AutoReconnect, PyMongoError
from requests.exceptions import ConnectionError as RequestsConnectionError

from benchmarks.stream_cost import topology
from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.topology import ReplicaSetTopology
from client_query_cache._types import BsonDict

if TYPE_CHECKING:
    from testcontainers.core.container import DockerContainer

pytestmark = pytest.mark.unit


class _FakeContainer:
    __slots__ = ("start_error", "stats_calls", "stopped")

    def __init__(self, *, start_error: DockerException | None = None) -> None:
        self.start_error = start_error
        self.stopped = False
        self.stats_calls = 0

    def with_command(self, _command: list[str]) -> Self:
        return self

    def with_kwargs(self, **_kwargs: object) -> Self:
        return self

    def start(self) -> None:
        if self.start_error is not None:
            raise self.start_error

    def stop(self) -> None:
        self.stopped = True

    def get_wrapped_container(self) -> _FakeContainer:
        return self

    def stats(self, *, stream: bool, one_shot: bool) -> object:
        assert stream is False
        assert one_shot is True
        self.stats_calls += 1
        if self.stats_calls < 3:
            raise RequestsConnectionError("stats socket reset")
        return {
            "cpu_stats": {"cpu_usage": {"total_usage": 1_500_000_000}},
            "memory_stats": {"usage": 4096},
        }


class _FakeMongoClient:
    __slots__ = ()

    hello_responses: ClassVar[list[BsonDict]] = []
    ping_calls = 0

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    def __class_getitem__(cls, _item: object) -> type[_FakeMongoClient]:
        return cls

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        return None

    @property
    def admin(self) -> Self:
        return self

    def command(self, name: str, *_args: object, **_kwargs: object) -> BsonDict:
        if name == "ping":
            type(self).ping_calls += 1
            if type(self).ping_calls == 1:
                raise PyMongoError("member is starting")
            return {}
        if name == "hello":
            return type(self).hello_responses.pop(0)
        return {}


class _StepdownMongoClient(_FakeMongoClient):
    __slots__ = ()

    @staticmethod
    def command(name: str, *_args: object, **_kwargs: object) -> BsonDict:
        if name == "replSetStepDown":
            raise AutoReconnect("primary connection closed")
        return {"primary": "127.0.0.1:27017"}


class _InvalidPortSocket:
    # Static methods preserve the socket API while keeping this stub stateless.
    __slots__ = ("closed",)

    def __init__(self) -> None:
        self.closed = False

    @staticmethod
    def bind(_address: tuple[str, int]) -> None:
        return None

    @staticmethod
    def getsockname() -> tuple[str, int]:
        return "127.0.0.1", 0

    def close(self) -> None:
        self.closed = True


def _started_topology(container: _FakeContainer | None = None) -> ReplicaSetTopology:
    replica_set_topology = ReplicaSetTopology()
    replica_set_topology._containers = cast(
        "tuple[DockerContainer, ...]", (container,) * 3
    )
    replica_set_topology._member_ports = (27017, 27018, 27019)
    replica_set_topology._uri = "mongodb://127.0.0.1:27017/?replicaSet=rs0"
    return replica_set_topology


def test_replica_set_topology_validates_container_counters_and_retries_stats() -> None:
    container = _FakeContainer()
    replica_set = _started_topology(container)

    assert replica_set.container_cpu_usage_seconds(0) == pytest.approx(1.5)
    assert replica_set.container_memory_usage_bytes(1) == 4096
    assert container.stats_calls == 4
    with pytest.raises(BenchmarkSetupError, match="member index 3"):
        replica_set.container_cpu_usage_seconds(3)


def test_replica_set_stats_fail_after_the_registered_retry_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replica_set = _started_topology(_FakeContainer())
    monkeypatch.setattr(topology, "_STATS_ATTEMPTS", 1)

    with pytest.raises(BenchmarkSetupError, match="stats socket reset"):
        replica_set.container_cpu_usage_seconds(0)


def test_successful_stepdown_catches_the_primary_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(topology, "MongoClient", _StepdownMongoClient)
    monkeypatch.setattr(topology, "monotonic", lambda: 4.2)

    assert _started_topology().step_down_primary() == pytest.approx(4.2)


def test_available_loopback_ports_reject_zero_and_close_the_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_socket = _InvalidPortSocket()
    monkeypatch.setattr(socket, "socket", lambda *_args: fake_socket)

    with pytest.raises(BenchmarkSetupError, match="invalid MongoDB member port"):
        topology._available_loopback_ports()

    assert fake_socket.closed


@pytest.mark.parametrize(
    "stats",
    [
        pytest.param(None, id="not-a-dict"),
        pytest.param({}, id="missing-counter"),
        pytest.param(
            {"cpu_stats": {"cpu_usage": {"total_usage": -1}}},
            id="negative-counter",
        ),
        pytest.param(
            {"cpu_stats": {"cpu_usage": {"total_usage": "bad"}}},
            id="malformed-counter",
        ),
        pytest.param(
            {"cpu_stats": {"cpu_usage": {"total_usage": float("inf")}}},
            id="overflow-counter",
        ),
    ],
)
def test_replica_set_topology_reports_unreadable_cpu_stats(
    stats: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ReplicaSetTopology,
        "_container_stats",
        lambda _self, _index: stats,
    )

    with pytest.raises(BenchmarkSetupError, match="CPU usage"):
        _started_topology().container_cpu_usage_seconds(0)


def test_replica_set_topology_reports_runtime_cpu_and_memory_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_self: ReplicaSetTopology, _index: int) -> object:
        raise DockerException("stats unavailable")

    monkeypatch.setattr(ReplicaSetTopology, "_container_stats", fail)
    with pytest.raises(BenchmarkSetupError, match="CPU usage"):
        _started_topology().container_cpu_usage_seconds(0)
    with pytest.raises(BenchmarkSetupError, match="memory usage"):
        _started_topology().container_memory_usage_bytes(0)


def test_replica_set_topology_requires_start_before_exposing_resources() -> None:
    replica_set = ReplicaSetTopology()
    with pytest.raises(BenchmarkSetupError, match="has not been started"):
        _ = replica_set.uri
    with pytest.raises(BenchmarkSetupError, match="has not been started"):
        _ = replica_set.member_containers
    with pytest.raises(BenchmarkSetupError, match="has not been started"):
        _ = replica_set.member_ports


def test_replica_set_topology_skips_transient_primary_election_responses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeMongoClient.hello_responses = [
        {"isWritablePrimary": False},
        {"isWritablePrimary": True},
    ]
    _FakeMongoClient.ping_calls = 0
    reachable: list[int] = []
    monkeypatch.setattr(topology, "MongoClient", _FakeMongoClient)
    monkeypatch.setattr(topology, "_await_member_reachable", reachable.append)

    _started_topology()._await_writable_primary()

    assert reachable == [27017, 27018, 27019]


def test_replica_set_topology_times_out_without_a_writable_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeMongoClient.hello_responses = []
    monkeypatch.setattr(topology, "MongoClient", _FakeMongoClient)
    monkeypatch.setattr(topology, "_await_member_reachable", lambda _port: None)
    monkeypatch.setattr(topology, "_ELECTION_TIMEOUT_SECONDS", 0.0)

    with pytest.raises(BenchmarkSetupError, match="did not elect a writable primary"):
        _started_topology()._await_writable_primary()


def test_member_reachability_retries_transient_driver_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeMongoClient.ping_calls = 0
    monkeypatch.setattr(topology, "MongoClient", _FakeMongoClient)
    monkeypatch.setattr(topology, "_ELECTION_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(topology, "sleep", lambda _seconds: None)

    topology._await_member_reachable(27017)

    assert _FakeMongoClient.ping_calls == 2


def test_member_reachability_reports_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeMongoClient.ping_calls = 0
    monkeypatch.setattr(topology, "MongoClient", _FakeMongoClient)
    monkeypatch.setattr(topology, "_ELECTION_TIMEOUT_SECONDS", 0.0)

    with pytest.raises(BenchmarkSetupError, match="did not become reachable"):
        topology._await_member_reachable(27017)


def test_failed_member_start_stops_already_created_containers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    containers: list[_FakeContainer] = []

    def create(_image: str) -> _FakeContainer:
        container = _FakeContainer(
            start_error=DockerException("member start failed") if containers else None
        )
        containers.append(container)
        return container

    monkeypatch.setattr(topology, "_available_loopback_ports", lambda: (1, 2, 3))
    monkeypatch.setattr(topology, "DockerContainer", create)

    with pytest.raises(BenchmarkSetupError, match="three-member replica set"):
        ReplicaSetTopology().__enter__()

    assert len(containers) == 2
    assert all(container.stopped for container in containers)


def test_primary_setup_failure_stops_and_clears_all_members(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    containers: list[_FakeContainer] = []

    def create(_image: str) -> _FakeContainer:
        container = _FakeContainer()
        containers.append(container)
        return container

    def fail(_self: ReplicaSetTopology) -> None:
        raise RuntimeError("primary setup failed")

    monkeypatch.setattr(topology, "_available_loopback_ports", lambda: (1, 2, 3))
    monkeypatch.setattr(topology, "DockerContainer", create)
    monkeypatch.setattr(ReplicaSetTopology, "_await_writable_primary", fail)
    replica_set = ReplicaSetTopology()

    with pytest.raises(RuntimeError, match="primary setup failed"):
        replica_set.__enter__()

    assert all(container.stopped for container in containers)
    with pytest.raises(BenchmarkSetupError, match="has not been started"):
        _ = replica_set.uri


def test_stop_containers_attaches_all_cleanup_failures_to_active_error() -> None:
    class FailingStop:
        def __init__(self, message: str) -> None:
            self.message = message

        def stop(self) -> None:
            raise DockerException(self.message)

    active_error = RuntimeError("setup failed")
    topology._stop_containers(
        cast(
            "tuple[DockerContainer, ...]", (FailingStop("first"), FailingStop("second"))
        ),
        active_error,
    )

    assert len(getattr(active_error, "__notes__", [])) == 2


def test_stop_containers_raises_first_failure_and_notes_later_failures() -> None:
    class FailingStop:
        def __init__(self, message: str) -> None:
            self.message = message

        def stop(self) -> None:
            raise DockerException(self.message)

    with pytest.raises(DockerException, match="second") as error:
        topology._stop_containers(
            cast(
                "tuple[DockerContainer, ...]",
                (FailingStop("first"), FailingStop("second")),
            ),
            None,
        )

    assert getattr(error.value, "__notes__", []) == ["first"]
