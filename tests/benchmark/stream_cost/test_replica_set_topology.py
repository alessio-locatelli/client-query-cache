from __future__ import annotations

import socket
from typing import TYPE_CHECKING, ClassVar, Self, cast

import pytest
from docker.errors import DockerException
from pymongo.errors import AutoReconnect

from benchmarks.stream_cost import topology as topology_module
from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.topology import (
    ReplicaSetTopology,
    _available_loopback_ports,
    _await_member_reachable,
    _stop_containers,
)
from client_query_cache._types import BsonDict, PositiveInt

if TYPE_CHECKING:
    from collections.abc import Sequence

    from testcontainers.core.container import DockerContainer

pytestmark = pytest.mark.unit
_FAKE_URI = "mongodb://127.0.0.1/?replicaSet=rs0"


class _FakeAdmin:
    __slots__ = ("responses",)

    def __init__(self, responses: list[object]) -> None:
        self.responses = responses

    def command(self, _name: str, *_args: object, **_kwargs: object) -> BsonDict:
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return cast("BsonDict", response)


class _FakeMongoClient:
    __slots__ = ("admin",)

    response_sets: ClassVar[list[list[object]]]

    def __class_getitem__(cls, _document: object) -> type[_FakeMongoClient]:
        return cls

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.admin = _FakeAdmin(type(self).response_sets.pop(0))

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        return None


class _FakeContainer:
    __slots__ = ("start_error", "stop_error", "stopped")

    def __init__(
        self,
        *,
        start_error: DockerException | None = None,
        stop_error: DockerException | None = None,
    ) -> None:
        self.start_error = start_error
        self.stop_error = stop_error
        self.stopped = False

    def with_command(self, _command: Sequence[str]) -> Self:
        return self

    def with_kwargs(self, **_kwargs: object) -> Self:
        return self

    def start(self) -> None:
        if self.start_error is not None:
            raise self.start_error

    def stop(self) -> None:
        self.stopped = True
        if self.stop_error is not None:
            raise self.stop_error


def test_replica_set_member_ports_are_distinct_and_released() -> None:
    ports = _available_loopback_ports()

    assert len(ports) == 3
    assert len(set(ports)) == 3
    for port in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", port))


def test_replica_set_topology_requires_start_before_use() -> None:
    topology = ReplicaSetTopology()

    with pytest.raises(BenchmarkSetupError, match="has not been started"):
        _ = topology.uri
    with pytest.raises(BenchmarkSetupError, match="has not been started"):
        topology.primary_identity()


def test_member_reachability_retries_transient_driver_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeMongoClient.response_sets = [[AutoReconnect("member is starting"), {}]]
    monkeypatch.setattr(topology_module, "MongoClient", _FakeMongoClient)
    monkeypatch.setattr(topology_module, "monotonic", iter((0.0, 0.0, 0.0)).__next__)
    monkeypatch.setattr(topology_module, "sleep", lambda _seconds: None)

    _await_member_reachable(27_017)


def test_member_reachability_reports_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeMongoClient.response_sets = [[]]
    monkeypatch.setattr(topology_module, "MongoClient", _FakeMongoClient)
    monkeypatch.setattr(topology_module, "monotonic", iter((0.0, 31.0)).__next__)

    with pytest.raises(BenchmarkSetupError, match="did not become reachable"):
        _await_member_reachable(27_017)


def test_container_cleanup_preserves_active_error_and_all_cleanup_errors() -> None:
    first = _FakeContainer(stop_error=DockerException("first cleanup failure"))
    second = _FakeContainer(stop_error=DockerException("second cleanup failure"))
    active_error = RuntimeError("replica-set setup failed")

    containers = cast("tuple[DockerContainer, ...]", (first, second))
    _stop_containers(containers, active_error)

    assert first.stopped
    assert second.stopped
    assert len(active_error.__notes__) == 2


def test_container_cleanup_raises_first_error_and_notes_later_error() -> None:
    first = _FakeContainer(stop_error=DockerException("first cleanup failure"))
    second = _FakeContainer(stop_error=DockerException("second cleanup failure"))
    containers = cast("tuple[DockerContainer, ...]", (first, second))

    with pytest.raises(DockerException, match="second cleanup failure") as error:
        _stop_containers(containers, None)

    assert first.stopped
    assert second.stopped
    assert error.value.__notes__ == ["first cleanup failure"]


def test_container_start_failure_stops_started_members(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = _FakeContainer(start_error=DockerException("container failed"))
    monkeypatch.setattr(
        topology_module,
        "_available_loopback_ports",
        lambda: (27_017,),
    )
    monkeypatch.setattr(topology_module, "DockerContainer", lambda _image: container)

    with pytest.raises(BenchmarkSetupError, match="container failed"):
        ReplicaSetTopology().__enter__()

    assert container.stopped


def test_primary_setup_failure_stops_members_and_clears_topology(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    containers = [_FakeContainer() for _ in range(3)]
    remaining = iter(containers)
    monkeypatch.setattr(
        topology_module,
        "_available_loopback_ports",
        lambda: cast("tuple[PositiveInt, ...]", (27_017, 27_018, 27_019)),
    )
    monkeypatch.setattr(
        topology_module, "DockerContainer", lambda _image: next(remaining)
    )

    def fail_primary(_topology: ReplicaSetTopology) -> None:
        raise BenchmarkSetupError("election did not complete")

    monkeypatch.setattr(ReplicaSetTopology, "_await_writable_primary", fail_primary)
    topology = ReplicaSetTopology()

    with pytest.raises(BenchmarkSetupError, match="election did not complete"):
        topology.__enter__()

    assert all(container.stopped for container in containers)
    with pytest.raises(BenchmarkSetupError, match="has not been started"):
        _ = topology.uri


def test_primary_wait_retries_election_until_a_member_is_writable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeMongoClient.response_sets = [
        [
            {"isWritablePrimary": False},
            AutoReconnect("election in progress"),
            {"isWritablePrimary": True, "me": "127.0.0.1:27017"},
        ]
    ]
    monkeypatch.setattr(topology_module, "MongoClient", _FakeMongoClient)
    monkeypatch.setattr(
        topology_module, "monotonic", iter((0.0, 0.0, 0.0, 0.0)).__next__
    )
    monkeypatch.setattr(topology_module, "sleep", lambda _seconds: None)
    topology = ReplicaSetTopology()
    topology._uri = _FAKE_URI

    assert topology.await_writable_primary() == "127.0.0.1:27017"


def test_primary_wait_reports_election_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeMongoClient.response_sets = [[]]
    monkeypatch.setattr(topology_module, "MongoClient", _FakeMongoClient)
    monkeypatch.setattr(topology_module, "monotonic", iter((0.0, 31.0)).__next__)
    topology = ReplicaSetTopology()
    topology._uri = _FAKE_URI

    with pytest.raises(BenchmarkSetupError, match="did not elect a writable primary"):
        topology.await_writable_primary()


def test_stepdown_treats_primary_disconnect_as_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeMongoClient.response_sets = [
        [{"me": "127.0.0.1:27017"}],
        [AutoReconnect("primary stepped down")],
    ]
    monkeypatch.setattr(topology_module, "MongoClient", _FakeMongoClient)
    topology = ReplicaSetTopology()
    topology._uri = _FAKE_URI

    assert topology.step_down_primary() == "127.0.0.1:27017"
