from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from client_query_cache import CacheConfigurationError, CacheCore, CacheCoreConfig
from client_query_cache._core import native
from client_query_cache._core.codec import encode_value
from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.stream_events import route_change_event
from client_query_cache._shared_index import SharedOwnerCore
from client_query_cache._types import NonEmptyStr
from client_query_cache.shared import SharedCacheConfig

if TYPE_CHECKING:
    from collections.abc import Iterator

    from client_query_cache._core.contracts import LocalCacheCore as Core
    from client_query_cache._core.keys import NamespaceId

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("config_type", [CacheCoreConfig, SharedCacheConfig])
@pytest.mark.parametrize("enabled", [False, True], ids=["disabled", "enabled"])
def test_configuration_preserves_exact_boolean_policy(
    config_type: type[CacheCoreConfig | SharedCacheConfig], *, enabled: bool
) -> None:
    assert config_type().enable_telemetry is False
    assert config_type(enable_telemetry=enabled).enable_telemetry is enabled


@pytest.mark.parametrize("config_type", [CacheCoreConfig, SharedCacheConfig])
@pytest.mark.parametrize(
    "invalid",
    [1, None, "true", 0.0, object()],
    ids=["integer", "null", "string", "float", "object"],
)
def test_configuration_rejects_non_boolean_policy(
    config_type: type[CacheCoreConfig | SharedCacheConfig], invalid: object
) -> None:
    with pytest.raises(CacheConfigurationError, match="enable_telemetry"):
        config_type(enable_telemetry=invalid)  # type: ignore[arg-type]


@pytest.fixture
def unexpected_observation() -> Mock:
    return Mock(side_effect=AssertionError("disabled operation prepared telemetry"))


@pytest.fixture(params=["native", "owner"])
def disabled_core(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    unexpected_observation: Mock,
) -> Iterator[Core]:
    monkeypatch.setattr(native, "StreamCostRegistry", unexpected_observation)
    config = CacheCoreConfig(
        budget_bytes=120, max_entry_bytes=60, max_entries=2, max_key_bytes=4096
    )
    if request.param == "native":
        core: Core = CacheCore(config)
    else:
        core = SharedOwnerCore(config, None, ["test_db"], 4, 30.0)
    yield core
    core.close()


@pytest.fixture(params=[False, True], ids=["open", "closed"])
def inspected_disabled_core(
    disabled_core: Core, request: pytest.FixtureRequest
) -> Core:
    if request.param:
        disabled_core.close()
    return disabled_core


@pytest.mark.parametrize(
    ("method", "arguments"),
    [
        ("snapshot", ()),
        ("stream_cost_snapshot", ("test_db",)),
        ("active_stream_cost_databases", ()),
        ("reset_stream_cost_statistics", ()),
        ("reset_stream_cost_statistics", ("test_db",)),
    ],
    ids=["cache", "stream-cost", "databases", "reset-all", "reset-database"],
)
def test_disabled_diagnostics_reject_before_building_reports(
    inspected_disabled_core: Core,
    method: NonEmptyStr,
    arguments: tuple[object, ...],
) -> None:
    with pytest.raises(CacheConfigurationError, match="enable_telemetry=True"):
        getattr(inspected_disabled_core, method)(*arguments)


def test_default_reads_enforce_limits_and_invalidate_without_collectors(
    disabled_core: Core, namespace: NamespaceId
) -> None:
    assert disabled_core.enable_telemetry is False
    assert not disabled_core.lookup_identity(namespace, "absent", "full").hit
    for identity in ("first", "second", "third"):
        capture = disabled_core.begin_identity_admission(namespace, identity)
        assert (
            disabled_core.admit_identity(capture, "full", identity)
            is AdmissionOutcome.ADMITTED
        )
    assert not disabled_core.lookup_identity(namespace, "first", "full").hit
    assert disabled_core.lookup_identity(namespace, "third", "full").value == "third"
    oversized = disabled_core.begin_identity_admission(namespace, "oversized")
    assert (
        disabled_core.admit_identity_encoded(oversized, "full", encode_value("x" * 100))
        is AdmissionOutcome.DECLINED_OVERSIZE
    )
    route_change_event(
        disabled_core,
        namespace.database,
        {
            "operationType": "update",
            "ns": {"db": namespace.database, "coll": namespace.collection},
            "documentKey": {"_id": "third"},
        },
    )
    assert not disabled_core.lookup_identity(namespace, "third", "full").hit
    disabled_core.record_miss()
    disabled_core.record_bypass()
    disabled_core.record_oversized_bypass()
    disabled_core.record_stream_poll(namespace.database)
    disabled_core.record_logical_event_bytes(namespace.database, 10)
    disabled_core.record_invalidation_applied(namespace.database, 0.0, 0.0, 0.0)


@pytest.fixture(params=[False, True], ids=["open", "closed"])
def unmeasured_owner_history(
    request: pytest.FixtureRequest,
) -> Iterator[SharedOwnerCore]:
    core = SharedOwnerCore(CacheCoreConfig(), None, ["db"], 1, 30.0)
    if request.param:
        core.close()
    yield core
    core.close()


def test_disabled_owner_history_rejects_before_locking(
    unmeasured_owner_history: SharedOwnerCore,
) -> None:
    with pytest.raises(CacheConfigurationError, match="enable_telemetry=True"):
        unmeasured_owner_history.available_since("db")
