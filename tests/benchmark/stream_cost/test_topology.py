from __future__ import annotations

from typing import Any, ClassVar, Self
from unittest.mock import patch

import pytest
from docker.errors import DockerException
from pymongo.errors import PyMongoError
from testcontainers.core.exceptions import ContainerStartException

from benchmarks.stream_cost.client import BenchmarkClientTopologyConfig, WireCompressor
from benchmarks.stream_cost.errors import (
    BenchmarkConfigurationError,
    BenchmarkSetupError,
)
from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits

pytestmark = pytest.mark.unit


class _FakeStats:
    __slots__ = ("_stats_result",)

    def __init__(self, stats_result: object) -> None:
        self._stats_result = stats_result

    def stats(self, *, stream: bool) -> object:
        assert stream is False
        if self._stats_result is None:
            raise DockerException("stats unavailable")
        return self._stats_result


class _FakeContainer:
    __slots__ = ("_fail_stop", "_wrapped", "stopped")

    def __init__(self, stats_result: object, *, fail_stop: bool = False) -> None:
        self._wrapped = _FakeStats(stats_result)
        self.stopped = False
        self._fail_stop = fail_stop

    def get_wrapped_container(self) -> _FakeStats:
        return self._wrapped

    def stop(self) -> None:
        self.stopped = True
        if self._fail_stop:
            raise DockerException("stop failed")


class _FakeMongoClient:
    __slots__ = ()

    def __class_getitem__(cls, item: object) -> type[_FakeMongoClient]:
        return cls

    def __init__(self, uri: str, **kwargs: object) -> None:
        pass

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        return None

    @property
    def admin(self) -> Self:
        return self


class _StubHelloClient(_FakeMongoClient):
    __slots__ = ()

    @staticmethod
    def command(name: str, *_args: object, **_kwargs: object) -> dict[str, object]:
        if name == "hello":
            return {"isWritablePrimary": False}
        return {}


@pytest.mark.parametrize(
    ("cpus", "memory", "match"),
    [
        (0, "512m", "cpus must be positive"),
        (-1.0, "512m", "cpus must be positive"),
        (1.0, "", "memory must not be empty"),
        (1e-15, "512m", "too small to represent as a positive nanocpu count"),
        (float("nan"), "512m", "cpus must be a finite number"),
        (float("inf"), "512m", "cpus must be a finite number"),
        (1e308, "512m", "overflows the container runtime's nanocpu representation"),
        (1.0, "0", "must be a positive quantity"),
        (1.0, "0m", "must be a positive quantity"),
        (1.0, "not-a-memory-quantity", "not a valid Docker memory quantity"),
        (1.0, "1" + "0" * 400, "non-finite byte quantity"),
    ],
)
def test_resource_limits_rejects_invalid_values(
    cpus: float, memory: str, match: str
) -> None:
    with pytest.raises(BenchmarkConfigurationError, match=match):
        ResourceLimits(cpus=cpus, memory=memory)


@pytest.mark.parametrize("memory", ["512m", "512mb", "1g", "1gb", "1024k", "1024kb"])
def test_resource_limits_accepts_docker_memory_suffixes(memory: str) -> None:
    ResourceLimits(cpus=1.0, memory=memory)


def test_isolated_replica_set_wraps_docker_startup_failure() -> None:
    replica_set = IsolatedReplicaSet(ResourceLimits(cpus=1.0, memory="512m"))
    with (
        patch(
            "benchmarks.stream_cost.topology.DockerContainer",
            side_effect=DockerException("no runtime"),
        ),
        pytest.raises(BenchmarkSetupError, match="Docker-compatible container runtime"),
    ):
        replica_set.__enter__()


class _FakeDockerContainer:
    __slots__ = ("_fail_start_exception", "_fail_stop", "stopped")

    def __init__(
        self,
        *,
        fail_start_exception: type[Exception] | None = None,
        fail_stop: bool = False,
    ) -> None:
        self.stopped = False
        self._fail_start_exception = fail_start_exception
        self._fail_stop = fail_stop

    def with_command(self, _command: object) -> _FakeDockerContainer:
        return self

    def with_exposed_ports(self, *_ports: int) -> _FakeDockerContainer:
        return self

    def with_kwargs(self, **_kwargs: object) -> _FakeDockerContainer:
        return self

    def start(self) -> _FakeDockerContainer:
        if self._fail_start_exception is not None:
            raise self._fail_start_exception("start failed")
        return self

    @staticmethod
    def get_container_host_ip() -> str:
        return "127.0.0.1"

    @staticmethod
    def get_exposed_port(port: int) -> int:
        return port

    def stop(self) -> None:
        self.stopped = True
        if self._fail_stop:
            raise DockerException("stop failed")


def _raise_setup_error(_self: IsolatedReplicaSet) -> None:
    raise BenchmarkSetupError("boom")


@pytest.mark.parametrize(
    "fail_stop",
    [pytest.param(False, id="stop_succeeds"), pytest.param(True, id="stop_also_fails")],
)
def test_enter_stops_container_when_post_start_setup_fails(
    monkeypatch: pytest.MonkeyPatch, fail_stop: bool
) -> None:
    fake_container = _FakeDockerContainer(fail_stop=fail_stop)
    monkeypatch.setattr(
        "benchmarks.stream_cost.topology.DockerContainer",
        lambda _image: fake_container,
    )
    monkeypatch.setattr(
        IsolatedReplicaSet, "_await_writable_primary", _raise_setup_error
    )
    replica_set = IsolatedReplicaSet(ResourceLimits(cpus=1.0, memory="512m"))
    with pytest.raises(BenchmarkSetupError, match="boom"):
        replica_set.__enter__()
    assert fake_container.stopped is True
    with pytest.raises(BenchmarkSetupError, match="has not been started"):
        _ = replica_set.uri


@pytest.mark.parametrize("start_exception", [DockerException, ContainerStartException])
def test_enter_stops_partially_created_container_when_start_fails(
    monkeypatch: pytest.MonkeyPatch, start_exception: type[Exception]
) -> None:
    fake_container = _FakeDockerContainer(fail_start_exception=start_exception)
    monkeypatch.setattr(
        "benchmarks.stream_cost.topology.DockerContainer",
        lambda _image: fake_container,
    )
    replica_set = IsolatedReplicaSet(ResourceLimits(cpus=1.0, memory="512m"))
    with pytest.raises(
        BenchmarkSetupError, match="Docker-compatible container runtime"
    ):
        replica_set.__enter__()
    assert fake_container.stopped is True


def test_uri_before_start_raises() -> None:
    replica_set = IsolatedReplicaSet(ResourceLimits(cpus=1.0, memory="512m"))
    with pytest.raises(BenchmarkSetupError, match="has not been started"):
        _ = replica_set.uri


def test_cpu_usage_before_start_raises() -> None:
    replica_set = IsolatedReplicaSet(ResourceLimits(cpus=1.0, memory="512m"))
    with pytest.raises(BenchmarkSetupError, match="has not been started"):
        replica_set.container_cpu_usage_seconds()


def test_cpu_usage_reads_docker_stats() -> None:
    replica_set = IsolatedReplicaSet(ResourceLimits(cpus=1.0, memory="512m"))
    replica_set._container = _FakeContainer(  # type: ignore[assignment]
        {"cpu_stats": {"cpu_usage": {"total_usage": 2_000_000_000}}}
    )
    assert replica_set.container_cpu_usage_seconds() == pytest.approx(2.0)


@pytest.mark.parametrize(
    "stats",
    [
        None,
        {},
        {"cpu_stats": {}},
        {"cpu_stats": {"cpu_usage": {}}},
        {"cpu_stats": {"cpu_usage": {"total_usage": "not-a-number"}}},
        {"cpu_stats": {"cpu_usage": {"total_usage": float("nan")}}},
        {"cpu_stats": {"cpu_usage": {"total_usage": float("inf")}}},
        {"cpu_stats": {"cpu_usage": {"total_usage": -1}}},
        pytest.param(iter(()), id="non_dict_stats"),
    ],
)
def test_cpu_usage_wraps_missing_evidence(stats: object) -> None:
    replica_set = IsolatedReplicaSet(ResourceLimits(cpus=1.0, memory="512m"))
    replica_set._container = _FakeContainer(stats)  # type: ignore[assignment]
    with pytest.raises(BenchmarkSetupError, match="cgroup/stats evidence"):
        replica_set.container_cpu_usage_seconds()


def test_exit_without_start_is_a_noop() -> None:
    replica_set = IsolatedReplicaSet(ResourceLimits(cpus=1.0, memory="512m"))
    replica_set.__exit__()


def test_exit_stops_the_container() -> None:
    replica_set = IsolatedReplicaSet(ResourceLimits(cpus=1.0, memory="512m"))
    fake_container = _FakeContainer({"cpu_stats": {"cpu_usage": {"total_usage": 0}}})
    replica_set._container = fake_container  # type: ignore[assignment]
    replica_set._uri = "mongodb://stub/"
    replica_set.__exit__()
    assert fake_container.stopped is True
    with pytest.raises(BenchmarkSetupError, match="has not been started"):
        _ = replica_set.uri


def test_exit_surfaces_stop_failure_when_no_exception_is_active() -> None:
    replica_set = IsolatedReplicaSet(ResourceLimits(cpus=1.0, memory="512m"))
    fake_container = _FakeContainer(
        {"cpu_stats": {"cpu_usage": {"total_usage": 0}}}, fail_stop=True
    )
    replica_set._container = fake_container  # type: ignore[assignment]
    replica_set._uri = "mongodb://stub/"
    with pytest.raises(DockerException, match="stop failed"):
        replica_set.__exit__()
    assert fake_container.stopped is True
    with pytest.raises(BenchmarkSetupError, match="has not been started"):
        _ = replica_set.uri


def test_exit_suppresses_stop_failure_when_an_exception_is_already_active() -> None:
    replica_set = IsolatedReplicaSet(ResourceLimits(cpus=1.0, memory="512m"))
    fake_container = _FakeContainer(
        {"cpu_stats": {"cpu_usage": {"total_usage": 0}}}, fail_stop=True
    )
    replica_set._container = fake_container  # type: ignore[assignment]
    replica_set._uri = "mongodb://stub/"
    body_error = RuntimeError("benchmark body failed")
    replica_set.__exit__(RuntimeError, body_error, None)
    assert fake_container.stopped is True
    assert any(
        "container cleanup failed" in note
        for note in getattr(body_error, "__notes__", [])
    )
    with pytest.raises(BenchmarkSetupError, match="has not been started"):
        _ = replica_set.uri


def test_exit_tolerates_a_missing_exception_instance() -> None:
    replica_set = IsolatedReplicaSet(ResourceLimits(cpus=1.0, memory="512m"))
    fake_container = _FakeContainer(
        {"cpu_stats": {"cpu_usage": {"total_usage": 0}}}, fail_stop=True
    )
    replica_set._container = fake_container  # type: ignore[assignment]
    replica_set._uri = "mongodb://stub/"
    replica_set.__exit__(RuntimeError, None, None)
    assert fake_container.stopped is True
    with pytest.raises(BenchmarkSetupError, match="has not been started"):
        _ = replica_set.uri


def test_await_writable_primary_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "benchmarks.stream_cost.topology._ELECTION_TIMEOUT_SECONDS", 0.02
    )
    monkeypatch.setattr(
        "benchmarks.stream_cost.topology._ELECTION_POLL_INTERVAL_SECONDS", 0.001
    )
    monkeypatch.setattr("benchmarks.stream_cost.topology.MongoClient", _StubHelloClient)
    replica_set = IsolatedReplicaSet(ResourceLimits(cpus=1.0, memory="512m"))
    replica_set._uri = "mongodb://stub/"
    with pytest.raises(BenchmarkSetupError, match="did not elect a writable primary"):
        replica_set._await_writable_primary()


class _CapturingHelloClient(_FakeMongoClient):
    __slots__ = ()
    captured: ClassVar[dict[str, Any]] = {}

    def command(self, name: str, *args: object, **_kwargs: object) -> dict[str, object]:
        if name == "replSetInitiate":
            type(self).captured["replSetInitiate"] = args[0]
            return {}
        if name == "hello":
            return {"isWritablePrimary": True}
        return {}


def test_await_writable_primary_advertises_the_containers_own_listening_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _CapturingHelloClient.captured.clear()
    monkeypatch.setattr(
        "benchmarks.stream_cost.topology.MongoClient", _CapturingHelloClient
    )
    replica_set = IsolatedReplicaSet(ResourceLimits(cpus=1.0, memory="512m"))
    replica_set._uri = "mongodb://stub/"
    replica_set._await_writable_primary()
    document = _CapturingHelloClient.captured["replSetInitiate"]
    assert document["members"][0]["host"] == "localhost:27017"


class _FlakyPingClient(_FakeMongoClient):
    __slots__ = ()
    ping_attempts: ClassVar[int] = 0

    def command(
        self, name: str, *_args: object, **_kwargs: object
    ) -> dict[str, object]:
        if name == "ping":
            type(self).ping_attempts += 1
            if type(self).ping_attempts < 3:
                raise PyMongoError("not ready yet")
            return {}
        if name == "hello":
            return {"isWritablePrimary": True}
        return {}


def test_await_writable_primary_retries_ping_until_reachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FlakyPingClient.ping_attempts = 0
    monkeypatch.setattr(
        "benchmarks.stream_cost.topology._ELECTION_POLL_INTERVAL_SECONDS", 0.001
    )
    monkeypatch.setattr("benchmarks.stream_cost.topology.MongoClient", _FlakyPingClient)
    replica_set = IsolatedReplicaSet(ResourceLimits(cpus=1.0, memory="512m"))
    replica_set._uri = "mongodb://stub/"
    replica_set._await_writable_primary()
    assert _FlakyPingClient.ping_attempts == 3


class _FlakyElectionClient(_FakeMongoClient):
    __slots__ = ()
    hello_attempts: ClassVar[int] = 0

    def command(
        self, name: str, *_args: object, **_kwargs: object
    ) -> dict[str, object]:
        if name == "hello":
            type(self).hello_attempts += 1
            if type(self).hello_attempts < 3:
                raise PyMongoError("election in progress")
            return {"isWritablePrimary": True}
        return {}


def test_await_writable_primary_retries_transient_hello_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FlakyElectionClient.hello_attempts = 0
    monkeypatch.setattr(
        "benchmarks.stream_cost.topology._ELECTION_POLL_INTERVAL_SECONDS", 0.001
    )
    monkeypatch.setattr(
        "benchmarks.stream_cost.topology.MongoClient", _FlakyElectionClient
    )
    replica_set = IsolatedReplicaSet(ResourceLimits(cpus=1.0, memory="512m"))
    replica_set._uri = "mongodb://stub/"
    replica_set._await_writable_primary()
    assert _FlakyElectionClient.hello_attempts == 3


class _UnreachablePingClient(_FakeMongoClient):
    __slots__ = ()

    @staticmethod
    def command(_name: str, *_args: object, **_kwargs: object) -> dict[str, object]:
        raise PyMongoError("unreachable")


def test_await_writable_primary_times_out_waiting_for_reachability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "benchmarks.stream_cost.topology._ELECTION_TIMEOUT_SECONDS", 0.02
    )
    monkeypatch.setattr(
        "benchmarks.stream_cost.topology._ELECTION_POLL_INTERVAL_SECONDS", 0.001
    )
    monkeypatch.setattr(
        "benchmarks.stream_cost.topology.MongoClient", _UnreachablePingClient
    )
    replica_set = IsolatedReplicaSet(ResourceLimits(cpus=1.0, memory="512m"))
    replica_set._uri = "mongodb://stub/"
    with pytest.raises(BenchmarkSetupError, match="did not become reachable"):
        replica_set._await_writable_primary()


def _client_topology(**overrides: object) -> BenchmarkClientTopologyConfig:
    defaults: dict[str, object] = {
        "tls_enabled": False,
        "compressor": WireCompressor.NONE,
        "discovery_enabled": False,
        "shared_connections": False,
    }
    defaults.update(overrides)
    return BenchmarkClientTopologyConfig(**defaults)  # type: ignore[arg-type]


def test_build_client_rejects_discovery() -> None:
    replica_set = IsolatedReplicaSet(ResourceLimits(cpus=1.0, memory="512m"))
    replica_set._uri = "mongodb://stub/"
    with pytest.raises(
        BenchmarkConfigurationError, match="topology discovery is not supported"
    ):
        replica_set.build_client(_client_topology(discovery_enabled=True))


def test_build_client_delegates_when_discovery_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def _fake_build_dedicated_client(
        uri: str, config: BenchmarkClientTopologyConfig, *, event_listeners: object = ()
    ) -> str:
        captured["uri"] = uri
        captured["config"] = config
        captured["event_listeners"] = event_listeners
        return "fake-client"

    monkeypatch.setattr(
        "benchmarks.stream_cost.topology.build_dedicated_client",
        _fake_build_dedicated_client,
    )
    replica_set = IsolatedReplicaSet(ResourceLimits(cpus=1.0, memory="512m"))
    replica_set._uri = "mongodb://stub/"
    config = _client_topology()
    client = replica_set.build_client(config)
    assert client == "fake-client"
    assert captured == {
        "uri": "mongodb://stub/",
        "config": config,
        "event_listeners": (),
    }


def test_build_client_passes_through_event_listeners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def _fake_build_dedicated_client(
        _uri: str,
        _config: BenchmarkClientTopologyConfig,
        *,
        event_listeners: object = (),
    ) -> str:
        captured["event_listeners"] = event_listeners
        return "fake-client"

    monkeypatch.setattr(
        "benchmarks.stream_cost.topology.build_dedicated_client",
        _fake_build_dedicated_client,
    )
    replica_set = IsolatedReplicaSet(ResourceLimits(cpus=1.0, memory="512m"))
    replica_set._uri = "mongodb://stub/"
    listener = object()
    replica_set.build_client(_client_topology(), event_listeners=[listener])
    assert captured["event_listeners"] == [listener]
