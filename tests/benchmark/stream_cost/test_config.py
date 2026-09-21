from __future__ import annotations

import dataclasses

import pytest

from benchmarks.stream_cost.config import (
    BenchmarkConfig,
    BenchmarkEnvironment,
    BenchmarkIdentity,
    Limitation,
    WorkloadParameters,
)
from benchmarks.stream_cost.errors import BenchmarkConfigurationError

pytestmark = pytest.mark.unit


def _identity(**overrides: str) -> BenchmarkIdentity:
    defaults = {
        "revision": "abc123",
        "library_version": "0.1.0",
        "python_version": "3.14.6",
        "pymongo_version": "4.18.0",
    }
    defaults.update(overrides)
    return BenchmarkIdentity(**defaults)


def _environment(**overrides: object) -> BenchmarkEnvironment:
    defaults: dict[str, object] = {
        "mongodb_version": "8.0.4",
        "topology": "replica-set",
        "member_count": 1,
        "resource_limits": {"cpu": "1"},
    }
    defaults.update(overrides)
    return BenchmarkEnvironment(**defaults)  # type: ignore[arg-type]


def _workload(**overrides: object) -> WorkloadParameters:
    defaults: dict[str, object] = {
        "name": "idle",
        "parameters": {"duration_seconds": 30},
    }
    defaults.update(overrides)
    return WorkloadParameters(**defaults)  # type: ignore[arg-type]


def test_benchmark_identity_accepts_valid_fields() -> None:

    assert _identity().revision == "abc123"


@pytest.mark.parametrize(
    "field_name", ["revision", "library_version", "python_version", "pymongo_version"]
)
def test_benchmark_identity_rejects_an_empty_field(field_name: str) -> None:
    with pytest.raises(BenchmarkConfigurationError):
        _identity(**{field_name: ""})


def test_benchmark_environment_accepts_valid_fields() -> None:

    assert _environment().member_count == 1


def test_benchmark_environment_resource_limits_are_not_mutable_via_the_input() -> None:
    resource_limits = {"cpu": "1"}
    environment = _environment(resource_limits=resource_limits)

    resource_limits["cpu"] = "2"

    assert environment.resource_limits["cpu"] == "1"
    with pytest.raises(TypeError):
        environment.resource_limits["cpu"] = "3"  # type: ignore[index]


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        pytest.param(
            {"mongodb_version": ""}, "mongodb_version", id="empty_mongodb_version"
        ),
        pytest.param({"topology": ""}, "topology", id="empty_topology"),
        pytest.param({"member_count": 0}, "member_count", id="zero_member_count"),
        pytest.param({"member_count": -1}, "member_count", id="negative_member_count"),
        pytest.param(
            {"resource_limits": {}}, "resource_limits", id="empty_resource_limits"
        ),
    ],
)
def test_benchmark_environment_rejects_incomplete_data(
    overrides: dict[str, object], match: str
) -> None:
    with pytest.raises(BenchmarkConfigurationError, match=match):
        _environment(**overrides)


def test_workload_parameters_accepts_valid_fields() -> None:

    assert _workload().name == "idle"


def test_workload_parameters_are_not_mutable_via_the_input() -> None:
    parameters = {"duration_seconds": 30}
    workload = _workload(parameters=parameters)

    parameters["duration_seconds"] = 60

    assert workload.parameters["duration_seconds"] == 30
    with pytest.raises(TypeError):
        workload.parameters["duration_seconds"] = 90  # type: ignore[index]


@pytest.mark.parametrize(
    "value",
    [
        pytest.param({"nested": "dict"}, id="dict"),
        pytest.param([1, 2, 3], id="list"),
    ],
)
def test_workload_parameters_rejects_a_non_scalar_value(value: object) -> None:
    with pytest.raises(BenchmarkConfigurationError, match="JSON scalar"):
        _workload(parameters={"data": value})


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        pytest.param({"name": ""}, "name", id="empty_name"),
        pytest.param({"parameters": {}}, "parameters", id="empty_parameters"),
    ],
)
def test_workload_parameters_rejects_incomplete_data(
    overrides: dict[str, object], match: str
) -> None:
    with pytest.raises(BenchmarkConfigurationError, match=match):
        _workload(**overrides)


@pytest.mark.parametrize(
    ("label", "description"),
    [
        pytest.param("", "a description", id="empty_label"),
        pytest.param("a-label", "", id="empty_description"),
    ],
)
def test_limitation_rejects_incomplete_data(label: str, description: str) -> None:
    with pytest.raises(BenchmarkConfigurationError):
        Limitation(label=label, description=description)


def test_benchmark_config_is_immutable() -> None:
    config = BenchmarkConfig(
        identity=_identity(),
        environment=_environment(),
        workload=_workload(),
        limitations=(Limitation("clock-skew", "raw lag includes server-host skew"),),
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        config.workload = _workload(name="other")  # type: ignore[misc]
