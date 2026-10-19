from __future__ import annotations

import math
import re
import socket
from dataclasses import dataclass
from time import monotonic, sleep
from typing import TYPE_CHECKING, Self, cast

from docker.errors import DockerException
from pymongo import MongoClient
from pymongo.errors import AutoReconnect, PyMongoError
from requests.exceptions import ConnectionError as RequestsConnectionError
from testcontainers.core.container import DockerContainer

from benchmarks.mongodb_diagnostics import note_mongodb_startup_failure
from benchmarks.mongodb_image import MONGODB_IMAGE
from benchmarks.stream_cost.client import (
    BenchmarkClientTopologyConfig,
    build_dedicated_client,
)
from benchmarks.stream_cost.errors import (
    BenchmarkConfigurationError,
    BenchmarkSetupError,
)
from client_query_cache._types import (
    BsonDict,
    JsonDict,
    NonEmptyStr,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from types import TracebackType

_REPLICA_SET_NAME = "rs0"
_MONGODB_PORT = 27017
_REPLICA_SET_MEMBER_COUNT = 3
_REPLICA_SET_MEMORY = "1g"
_REPLICA_SET_CPUS = 1.0
_ELECTION_TIMEOUT_SECONDS = 30.0
_ELECTION_POLL_INTERVAL_SECONDS = 0.1
_NANOCPUS_PER_CPU = 1_000_000_000
_NANOSECONDS_PER_SECOND = 1_000_000_000
_STATS_ATTEMPTS = 3
_MEMORY_PATTERN = re.compile(r"^(\d+(?:\.\d+)?)(kb|mb|gb|b|k|m|g)?$", re.IGNORECASE)
_MEMORY_UNIT_MULTIPLIERS = {
    "": 1,
    "b": 1,
    "k": 1024,
    "kb": 1024,
    "m": 1024**2,
    "mb": 1024**2,
    "g": 1024**3,
    "gb": 1024**3,
}


def _parse_memory_bytes(memory: str) -> NonNegativeFloat:
    match = _MEMORY_PATTERN.match(memory.strip())
    if match is None:
        message = f"memory ({memory!r}) is not a valid Docker memory quantity"
        raise BenchmarkConfigurationError(message)
    unit = (match.group(2) or "").lower()
    multiplier = _MEMORY_UNIT_MULTIPLIERS[unit]
    value = float(match.group(1)) * multiplier
    if not math.isfinite(value):
        message = f"memory ({memory!r}) overflows to a non-finite byte quantity"
        raise BenchmarkConfigurationError(message)
    return value


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    cpus: PositiveFloat
    memory: NonEmptyStr

    def __post_init__(self) -> None:
        if not math.isfinite(self.cpus):
            message = "cpus must be a finite number"
            raise BenchmarkConfigurationError(message)
        if self.cpus <= 0:
            message = "cpus must be positive"
            raise BenchmarkConfigurationError(message)
        if not self.memory:
            message = "memory must not be empty"
            raise BenchmarkConfigurationError(message)
        if _parse_memory_bytes(self.memory) <= 0:
            message = f"memory ({self.memory!r}) must be a positive quantity"
            raise BenchmarkConfigurationError(message)
        nanocpus = self.cpus * _NANOCPUS_PER_CPU
        if not math.isfinite(nanocpus):
            message = (
                f"cpus ({self.cpus}) overflows the container runtime's nanocpu "
                "representation"
            )
            raise BenchmarkConfigurationError(message)
        if nanocpus < 1:
            message = (
                f"cpus ({self.cpus}) is too small to represent as a positive "
                "nanocpu count once converted for the container runtime"
            )
            raise BenchmarkConfigurationError(message)


def _cpu_usage_unreadable(error: Exception) -> BenchmarkSetupError:
    message = (
        "Could not read MongoDB container CPU usage from the container "
        f"runtime's cgroup/stats evidence: {error}"
    )
    return BenchmarkSetupError(message)


def _parse_cpu_usage_nanoseconds(stats: object) -> NonNegativeInt:
    if not isinstance(stats, dict):
        message = "stats(stream=False) unexpectedly returned an iterator"
        raise TypeError(message)
    usage_nanoseconds = int(stats["cpu_stats"]["cpu_usage"]["total_usage"])
    if usage_nanoseconds < 0:
        message = f"total_usage ({usage_nanoseconds}) must not be negative"
        raise ValueError(message)
    return usage_nanoseconds


def _await_member_reachable(port: PositiveInt) -> None:
    with MongoClient[BsonDict](
        f"mongodb://127.0.0.1:{port}/?directConnection=true",
        serverSelectionTimeoutMS=1_000,
    ) as client:
        deadline = monotonic() + _ELECTION_TIMEOUT_SECONDS
        while monotonic() < deadline:
            try:
                client.admin.command("ping")
            except PyMongoError:
                sleep(_ELECTION_POLL_INTERVAL_SECONDS)
            else:
                return
    message = (
        f"MongoDB did not become reachable within "
        f"{_ELECTION_TIMEOUT_SECONDS:.0f} seconds."
    )
    raise BenchmarkSetupError(message)


def _stop_containers(
    containers: tuple[DockerContainer, ...],
    active_error: BaseException | None,
) -> None:
    first_cleanup_error: DockerException | None = None
    for container in reversed(containers):
        try:
            container.stop()
        except DockerException as cleanup_error:
            if active_error is not None:
                message = (
                    f"additionally, MongoDB container cleanup failed: {cleanup_error}"
                )
                active_error.add_note(message)
            elif first_cleanup_error is None:
                first_cleanup_error = cleanup_error
            else:
                first_cleanup_error.add_note(str(cleanup_error))
    if first_cleanup_error is not None:
        raise first_cleanup_error


class IsolatedReplicaSet:
    __slots__ = ("_container", "_limits", "_uri")

    def __init__(self, limits: ResourceLimits) -> None:
        self._limits = limits
        self._container: DockerContainer | None = None
        self._uri: str | None = None

    def __enter__(self) -> Self:
        container: DockerContainer | None = None
        try:
            container = DockerContainer(MONGODB_IMAGE)
            # MongoDB: https://www.mongodb.com/docs/manual/reference/program/mongod/
            # --replSet: The default is no replica set. We override it because the
            # disposable runtime must support change streams.
            container.with_command(["--replSet", _REPLICA_SET_NAME])
            container.with_exposed_ports(_MONGODB_PORT)
            # https://docs.docker.com/engine/containers/resource_constraints/
            # nano_cpus/mem_limit: The default is no explicit per-container limit. We
            # override it because each benchmark must run under its declared CPU/memory
            # budget.
            container.with_kwargs(
                nano_cpus=int(self._limits.cpus * _NANOCPUS_PER_CPU),
                mem_limit=self._limits.memory,
            )
            container.start()
        except DockerException as error:
            if container is not None:
                try:
                    container.stop()
                except DockerException:
                    pass
            message = (
                "A Docker-compatible container runtime is required for the "
                "stream-cost benchmark's isolated replica set. Start Docker or a "
                "rootless Podman socket and try again. Container startup failed: "
                f"{error}"
            )
            raise BenchmarkSetupError(message) from None
        self._container = container
        try:
            host = container.get_container_host_ip()
            port = container.get_exposed_port(_MONGODB_PORT)
            # PyMongo 4.18:
            # https://pymongo.readthedocs.io/en/4.18.1/api/pymongo/mongo_client.html
            # directConnection: The default is false. We override it because discovery
            # would follow the internally advertised localhost address instead of the
            # mapped port.
            self._uri = f"mongodb://{host}:{port}/?directConnection=true"
            self._await_writable_primary()
        except Exception as error:
            try:
                note_mongodb_startup_failure(container, error)
            finally:
                try:
                    container.stop()
                except DockerException:
                    pass
                self._container = None
                self._uri = None
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc: BaseException | None = None,
        _tb: TracebackType | None = None,
    ) -> None:
        if self._container is None:
            return
        try:
            if exc_type is not None:
                try:
                    self._container.stop()
                except DockerException as cleanup_error:
                    if exc is not None:
                        exc.add_note(
                            f"additionally, container cleanup failed: {cleanup_error}"
                        )
            else:
                self._container.stop()
        finally:
            self._container = None
            self._uri = None

    @property
    def uri(self) -> str:
        if self._uri is None:
            message = "IsolatedReplicaSet has not been started"
            raise BenchmarkSetupError(message)
        return self._uri

    def build_client(
        self,
        config: BenchmarkClientTopologyConfig,
        *,
        event_listeners: Sequence[object] = (),
    ) -> MongoClient[BsonDict]:
        if config.discovery_enabled:
            message = (
                "topology discovery is not supported against this single-member, "
                "port-mapped isolated replica set: the driver would follow the "
                "replica set's internally advertised member address "
                f"(localhost:{_MONGODB_PORT}), not the host-mapped address this "
                "URI actually connects through"
            )
            raise BenchmarkConfigurationError(message)
        return build_dedicated_client(self.uri, config, event_listeners=event_listeners)

    def _await_writable_primary(self) -> None:
        with MongoClient[BsonDict](
            # serverSelectionTimeoutMS: The default is 30000 ms. We override it because
            # bounded startup polling needs short connection attempts.
            self.uri,
            serverSelectionTimeoutMS=1_000,
        ) as client:
            last_ping_error: PyMongoError | None = None
            deadline = monotonic() + _ELECTION_TIMEOUT_SECONDS
            while monotonic() < deadline:
                try:
                    client.admin.command("ping")
                    break
                except PyMongoError as error:
                    last_ping_error = error
                    sleep(_ELECTION_POLL_INTERVAL_SECONDS)
            else:
                message = (
                    f"MongoDB did not become reachable within "
                    f"{_ELECTION_TIMEOUT_SECONDS:.0f} seconds."
                )
                raise BenchmarkSetupError(message) from last_ping_error

            client.admin.command(
                "replSetInitiate",
                {
                    "_id": _REPLICA_SET_NAME,
                    "members": [{"_id": 0, "host": f"localhost:{_MONGODB_PORT}"}],
                },
            )
            deadline = monotonic() + _ELECTION_TIMEOUT_SECONDS
            while monotonic() < deadline:
                try:
                    if client.admin.command("hello")["isWritablePrimary"]:
                        return
                except PyMongoError:
                    pass
                sleep(_ELECTION_POLL_INTERVAL_SECONDS)
            message = (
                f"MongoDB did not elect a writable primary within "
                f"{_ELECTION_TIMEOUT_SECONDS:.0f} seconds."
            )
            raise BenchmarkSetupError(message)

    def _stats(self) -> object:
        if self._container is None:
            message = "IsolatedReplicaSet has not been started"
            raise BenchmarkSetupError(message)
        wrapped = self._container.get_wrapped_container()
        attempts = _STATS_ATTEMPTS
        while True:
            try:
                return wrapped.stats(stream=False, one_shot=True)
            except RequestsConnectionError as error:
                attempts -= 1
                if not attempts:
                    raise DockerException(str(error)) from error

    def container_cpu_usage_seconds(self) -> NonNegativeFloat:
        try:
            usage_nanoseconds = _parse_cpu_usage_nanoseconds(self._stats())
        except DockerException as error:
            raise _cpu_usage_unreadable(error) from None
        except KeyError as error:
            raise _cpu_usage_unreadable(error) from None
        except TypeError as error:
            raise _cpu_usage_unreadable(error) from None
        except ValueError as error:
            raise _cpu_usage_unreadable(error) from None
        except OverflowError as error:
            raise _cpu_usage_unreadable(error) from None
        return usage_nanoseconds / _NANOSECONDS_PER_SECOND

    def container_memory_usage_bytes(self) -> NonNegativeInt:
        try:
            stats = self._stats()
        except DockerException as error:
            message = f"Could not read MongoDB container memory usage: {error}"
            raise BenchmarkSetupError(message) from None
        memory_stats = cast(
            "dict[str, NonNegativeInt]", cast("JsonDict", stats)["memory_stats"]
        )
        return int(memory_stats["usage"])


class ReplicaSetTopology:
    __slots__ = ("_containers", "_limits", "_member_ports", "_uri")

    def __init__(self) -> None:
        self._containers: tuple[DockerContainer, ...] = ()
        self._limits = ResourceLimits(
            cpus=_REPLICA_SET_CPUS, memory=_REPLICA_SET_MEMORY
        )
        self._member_ports: tuple[PositiveInt, ...] = ()
        self._uri: str | None = None

    def __enter__(self) -> Self:
        ports = _available_loopback_ports()
        containers: list[DockerContainer] = []
        try:
            for port in ports:
                container = DockerContainer(MONGODB_IMAGE)
                containers.append(container)
                # MongoDB: https://www.mongodb.com/docs/manual/reference/program/mongod/
                # --replSet enables change streams; --port gives each host-networked
                # member a distinct socket; --bind_ip keeps the disposable set local.
                container.with_command(
                    [
                        "--replSet",
                        _REPLICA_SET_NAME,
                        "--port",
                        str(port),
                        "--bind_ip",
                        "127.0.0.1",
                    ]
                )
                # Docker resource constraints:
                # https://docs.docker.com/engine/containers/resource_constraints/
                # Each member is charged the same declared CPU and memory limit.
                container.with_kwargs(
                    network_mode="host",
                    nano_cpus=int(self._limits.cpus * _NANOCPUS_PER_CPU),
                    mem_limit=self._limits.memory,
                )
                container.start()
        except DockerException as error:
            setup_error = BenchmarkSetupError(
                "A Docker-compatible container runtime is required for the "
                "stream-cost benchmark's three-member replica set. Start Docker or a "
                "rootless Podman socket and try again. Container startup failed: "
                f"{error}"
            )
            _stop_containers(tuple(containers), setup_error)
            raise setup_error from None

        self._containers = tuple(containers)
        self._member_ports = ports
        self._uri = (
            "mongodb://"
            + ",".join(f"127.0.0.1:{port}" for port in ports)
            + f"/?replicaSet={_REPLICA_SET_NAME}"
        )
        try:
            self._await_writable_primary()
        except Exception as error:
            _stop_containers(self._containers, error)
            self._clear()
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc: BaseException | None = None,
        _tb: TracebackType | None = None,
    ) -> None:
        try:
            _stop_containers(self._containers, exc)
        finally:
            self._clear()

    @property
    def uri(self) -> str:
        if self._uri is None:
            message = "ReplicaSetTopology has not been started"
            raise BenchmarkSetupError(message)
        return self._uri

    @property
    def member_containers(self) -> tuple[DockerContainer, ...]:
        if len(self._containers) != _REPLICA_SET_MEMBER_COUNT:
            message = "ReplicaSetTopology has not been started"
            raise BenchmarkSetupError(message)
        return self._containers

    @property
    def member_ports(self) -> tuple[PositiveInt, ...]:
        if len(self._member_ports) != _REPLICA_SET_MEMBER_COUNT:
            message = "ReplicaSetTopology has not been started"
            raise BenchmarkSetupError(message)
        return self._member_ports

    def container_cpu_usage_seconds(
        self, member_index: NonNegativeInt
    ) -> NonNegativeFloat:
        try:
            stats = self._container_stats(member_index)
            usage_nanoseconds = _parse_cpu_usage_nanoseconds(stats)
        except DockerException as error:
            raise _cpu_usage_unreadable(error) from None
        except KeyError as error:
            raise _cpu_usage_unreadable(error) from None
        except TypeError as error:
            raise _cpu_usage_unreadable(error) from None
        except ValueError as error:
            raise _cpu_usage_unreadable(error) from None
        except OverflowError as error:
            raise _cpu_usage_unreadable(error) from None
        return usage_nanoseconds / _NANOSECONDS_PER_SECOND

    def container_memory_usage_bytes(
        self, member_index: NonNegativeInt
    ) -> NonNegativeInt:
        try:
            stats = cast(
                "dict[str, NonNegativeInt]",
                cast("JsonDict", self._container_stats(member_index))["memory_stats"],
            )
        except DockerException as error:
            message = f"Could not read MongoDB container memory usage: {error}"
            raise BenchmarkSetupError(message) from None
        return int(stats["usage"])

    def primary_identity(self) -> NonEmptyStr:
        with MongoClient[BsonDict](self.uri, serverSelectionTimeoutMS=1_000) as client:
            hello = client.admin.command("hello")
        return cast("NonEmptyStr", hello["primary"])

    def step_down_primary(self) -> NonNegativeFloat:
        primary_identity = self.primary_identity()
        with MongoClient[BsonDict](
            f"mongodb://{primary_identity}/?directConnection=true",
            serverSelectionTimeoutMS=1_000,
        ) as client:
            stepdown_started = monotonic()
            try:
                client.admin.command("replSetStepDown", 60)
            except AutoReconnect:
                # A successful stepdown closes the primary connection during election.
                pass
        return stepdown_started

    def _await_writable_primary(self) -> None:
        for port in self.member_ports:
            _await_member_reachable(port)

        first_port = self.member_ports[0]
        with MongoClient[BsonDict](
            f"mongodb://127.0.0.1:{first_port}/?directConnection=true",
            serverSelectionTimeoutMS=1_000,
        ) as initial_client:
            initial_client.admin.command(
                "replSetInitiate",
                {
                    "_id": _REPLICA_SET_NAME,
                    "members": [
                        {"_id": member_index, "host": f"127.0.0.1:{port}"}
                        for member_index, port in enumerate(self.member_ports)
                    ],
                },
            )

        deadline = monotonic() + _ELECTION_TIMEOUT_SECONDS
        with MongoClient[BsonDict](self.uri, serverSelectionTimeoutMS=1_000) as client:
            while monotonic() < deadline:
                try:
                    hello = client.admin.command("hello")
                    if hello["isWritablePrimary"]:
                        return
                except PyMongoError:
                    pass
                sleep(_ELECTION_POLL_INTERVAL_SECONDS)
        message = (
            f"MongoDB did not elect a writable primary within "
            f"{_ELECTION_TIMEOUT_SECONDS:.0f} seconds."
        )
        raise BenchmarkSetupError(message)

    def _container_stats(self, member_index: NonNegativeInt) -> object:
        if member_index >= len(self._containers):
            message = f"MongoDB member index {member_index} is not available"
            raise BenchmarkSetupError(message)
        wrapped = self._containers[member_index].get_wrapped_container()
        attempts = _STATS_ATTEMPTS
        while True:
            try:
                return wrapped.stats(stream=False, one_shot=True)
            except RequestsConnectionError as error:
                attempts -= 1
                if not attempts:
                    raise DockerException(str(error)) from error

    def _clear(self) -> None:
        self._containers = ()
        self._member_ports = ()
        self._uri = None


def _available_loopback_ports() -> tuple[PositiveInt, ...]:
    listeners: list[socket.socket] = []
    ports: list[PositiveInt] = []
    try:
        for _ in range(_REPLICA_SET_MEMBER_COUNT):
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listeners.append(listener)
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            if port <= 0:
                message = f"The OS allocated an invalid MongoDB member port: {port}"
                raise BenchmarkSetupError(message)
            ports.append(cast("PositiveInt", port))
    finally:
        for listener in listeners:
            listener.close()
    return tuple(ports)
