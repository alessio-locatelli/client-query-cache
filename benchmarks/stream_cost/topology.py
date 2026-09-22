from __future__ import annotations

import contextlib
import math
import re
from dataclasses import dataclass
from time import monotonic, sleep
from typing import TYPE_CHECKING, Self

from docker.errors import DockerException
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from testcontainers.core.container import DockerContainer
from testcontainers.core.exceptions import ContainerStartException

from benchmarks.stream_cost.client import (
    BenchmarkClientTopologyConfig,
    build_dedicated_client,
)
from benchmarks.stream_cost.errors import (
    BenchmarkConfigurationError,
    BenchmarkSetupError,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from types import TracebackType

MONGODB_IMAGE = "mongo:8.0.4-noble"

_REPLICA_SET_NAME = "rs0"
_MONGODB_PORT = 27017
_ELECTION_TIMEOUT_SECONDS = 30.0
_ELECTION_POLL_INTERVAL_SECONDS = 0.1
_NANOCPUS_PER_CPU = 1_000_000_000
_NANOSECONDS_PER_SECOND = 1_000_000_000
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


def _parse_memory_bytes(memory: str) -> float:
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
    cpus: float
    memory: str

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
            container.with_command(["--replSet", _REPLICA_SET_NAME, "--bind_ip_all"])
            container.with_exposed_ports(_MONGODB_PORT)
            container.with_kwargs(
                nano_cpus=int(self._limits.cpus * _NANOCPUS_PER_CPU),
                mem_limit=self._limits.memory,
            )
            container.start()
        except (DockerException, ContainerStartException) as error:
            if container is not None:
                with contextlib.suppress(DockerException, ContainerStartException):
                    container.stop()
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
            self._uri = f"mongodb://{host}:{port}/?directConnection=true"
            self._await_writable_primary()
        except Exception:
            with contextlib.suppress(DockerException, ContainerStartException):
                container.stop()
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
                except (DockerException, ContainerStartException) as cleanup_error:
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
    ) -> MongoClient[dict[str, object]]:
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
        with MongoClient[dict[str, object]](
            self.uri, serverSelectionTimeoutMS=1_000
        ) as client:
            deadline = monotonic() + _ELECTION_TIMEOUT_SECONDS
            while monotonic() < deadline:
                try:
                    client.admin.command("ping")
                    break
                except PyMongoError:
                    sleep(_ELECTION_POLL_INTERVAL_SECONDS)
            else:
                message = (
                    f"MongoDB did not become reachable within "
                    f"{_ELECTION_TIMEOUT_SECONDS:.0f} seconds."
                )
                raise BenchmarkSetupError(message)

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

    def container_cpu_usage_seconds(self) -> float:
        if self._container is None:
            message = "IsolatedReplicaSet has not been started"
            raise BenchmarkSetupError(message)
        try:
            wrapped = self._container.get_wrapped_container()
            stats = wrapped.stats(stream=False)
            usage_nanoseconds = self._parse_cpu_usage_nanoseconds(stats)
        except (
            DockerException,
            ContainerStartException,
            KeyError,
            TypeError,
            ValueError,
            OverflowError,
        ) as error:
            message = (
                "Could not read MongoDB container CPU usage from the container "
                f"runtime's cgroup/stats evidence: {error}"
            )
            raise BenchmarkSetupError(message) from None
        return usage_nanoseconds / _NANOSECONDS_PER_SECOND

    @staticmethod
    def _parse_cpu_usage_nanoseconds(stats: object) -> int:
        if not isinstance(stats, dict):
            message = "stats(stream=False) unexpectedly returned an iterator"
            raise TypeError(message)
        usage_nanoseconds = int(stats["cpu_stats"]["cpu_usage"]["total_usage"])
        if usage_nanoseconds < 0:
            message = f"total_usage ({usage_nanoseconds}) must not be negative"
            raise ValueError(message)
        return usage_nanoseconds
