from __future__ import annotations

from collections.abc import Mapping  # noqa: TC003 - Required for dataclass introspection.
from dataclasses import dataclass
from types import MappingProxyType

from benchmarks.stream_cost.errors import BenchmarkConfigurationError
from client_query_cache._types import NonEmpty, NonEmptyStr, PositiveInt

_JSONScalar = str | int | float | bool | None


def _require_non_empty_string(value: str, field_name: str) -> None:
    if not value:
        message = f"{field_name} must not be empty"
        raise BenchmarkConfigurationError(message)


def _require_scalar_values(mapping: Mapping[str, object], field_name: str) -> None:
    for key, value in mapping.items():
        if value is not None and not isinstance(value, (str, int, float, bool)):
            message = (
                f"{field_name}[{key!r}] must be a JSON scalar, got "
                f"{type(value).__name__}"
            )
            raise BenchmarkConfigurationError(message)


@dataclass(frozen=True, slots=True)
class BenchmarkIdentity:
    revision: NonEmptyStr
    library_version: NonEmptyStr
    python_version: NonEmptyStr
    pymongo_version: NonEmptyStr

    def __post_init__(self) -> None:
        _require_non_empty_string(self.revision, "revision")
        _require_non_empty_string(self.library_version, "library_version")
        _require_non_empty_string(self.python_version, "python_version")
        _require_non_empty_string(self.pymongo_version, "pymongo_version")


@dataclass(frozen=True, slots=True)
class BenchmarkEnvironment:
    mongodb_version: NonEmptyStr
    topology: NonEmptyStr
    member_count: PositiveInt
    resource_limits: NonEmpty[Mapping[str, str]]

    def __post_init__(self) -> None:
        _require_non_empty_string(self.mongodb_version, "mongodb_version")
        _require_non_empty_string(self.topology, "topology")
        if self.member_count <= 0:
            message = "member_count must be positive"
            raise BenchmarkConfigurationError(message)
        if not self.resource_limits:
            message = "resource_limits must not be empty"
            raise BenchmarkConfigurationError(message)
        object.__setattr__(
            self, "resource_limits", MappingProxyType(dict(self.resource_limits))
        )


@dataclass(frozen=True, slots=True)
class WorkloadParameters:
    name: NonEmptyStr
    parameters: NonEmpty[Mapping[str, _JSONScalar]]

    def __post_init__(self) -> None:
        _require_non_empty_string(self.name, "name")
        if not self.parameters:
            message = "parameters must not be empty"
            raise BenchmarkConfigurationError(message)
        _require_scalar_values(self.parameters, "parameters")
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))


@dataclass(frozen=True, slots=True)
class Limitation:
    label: NonEmptyStr
    description: NonEmptyStr

    def __post_init__(self) -> None:
        _require_non_empty_string(self.label, "label")
        _require_non_empty_string(self.description, "description")


@dataclass(frozen=True, slots=True)
class BenchmarkConfig:
    identity: BenchmarkIdentity
    environment: BenchmarkEnvironment
    workload: WorkloadParameters
    limitations: tuple[Limitation, ...]
