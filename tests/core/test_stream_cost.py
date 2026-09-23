from __future__ import annotations

import dataclasses
import datetime
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from bson.datetime_ms import DatetimeMS

from mongo_client_cache._core.errors import CacheConfigurationError
from mongo_client_cache._core.keys import NamespaceId
from mongo_client_cache._core.manager import CacheCore, CacheCoreConfig
from mongo_client_cache._core.stream_cost import (
    InvalidationApplyReading,
    LagCaptureWindowConfig,
    LagCaptureWindows,
)
from mongo_client_cache._core.stream_events import route_change_event

pytestmark = pytest.mark.unit

_WALL_TIME = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param(
            {"window_count": 0, "events_per_window": 1, "min_separation_events": 0},
            id="zero_window_count",
        ),
        pytest.param(
            {"window_count": 1, "events_per_window": 0, "min_separation_events": 0},
            id="zero_events_per_window",
        ),
        pytest.param(
            {"window_count": 1, "events_per_window": 1, "min_separation_events": -1},
            id="negative_separation",
        ),
    ],
)
def test_lag_capture_window_config_rejects_invalid_values(
    kwargs: dict[str, int],
) -> None:
    with pytest.raises(CacheConfigurationError):
        LagCaptureWindowConfig(**kwargs)


def test_lag_capture_windows_captures_fixed_contiguous_gap_free_blocks() -> None:
    config = LagCaptureWindowConfig(
        window_count=2, events_per_window=3, min_separation_events=0
    )
    windows = LagCaptureWindows(config)

    for value in range(9):
        windows.record(float(value))

    assert windows.snapshot() == ((3.0, 4.0, 5.0), (6.0, 7.0, 8.0))


def test_lag_capture_windows_enforces_minimum_separation_between_windows() -> None:
    config = LagCaptureWindowConfig(
        window_count=2, events_per_window=2, min_separation_events=2
    )
    windows = LagCaptureWindows(config)

    for value in range(8):
        windows.record(float(value))

    assert windows.snapshot() == ((0.0, 1.0), (4.0, 5.0))


def test_lag_capture_windows_retains_signed_values_without_clamping() -> None:
    config = LagCaptureWindowConfig(
        window_count=1, events_per_window=2, min_separation_events=0
    )
    windows = LagCaptureWindows(config)

    windows.record(-0.25)
    windows.record(-1.5)

    assert windows.snapshot() == ((-0.25, -1.5),)


def test_lag_capture_windows_stays_within_its_configured_memory_bound() -> None:
    config = LagCaptureWindowConfig(
        window_count=3, events_per_window=10, min_separation_events=0
    )
    windows = LagCaptureWindows(config)

    for value in range(10_000):
        windows.record(float(value))
        total_retained = sum(len(window) for window in windows._windows) + len(
            windows._current
        )
        assert total_retained <= config.window_count * config.events_per_window

    captured = windows.snapshot()
    assert len(captured) == config.window_count
    assert all(len(window) == config.events_per_window for window in captured)


def test_lag_capture_windows_record_reports_whether_the_event_was_accepted() -> None:
    config = LagCaptureWindowConfig(
        window_count=1, events_per_window=1, min_separation_events=1
    )
    windows = LagCaptureWindows(config)

    assert windows.record(1.0) is True
    assert windows.record(2.0) is False
    assert windows.record(3.0) is True


def test_lag_capture_windows_reset_clears_completed_and_partial_state() -> None:
    config = LagCaptureWindowConfig(
        window_count=2, events_per_window=2, min_separation_events=0
    )
    windows = LagCaptureWindows(config)
    windows.record(1.0)
    windows.record(2.0)
    windows.record(3.0)

    windows.reset()

    assert windows.snapshot() == ()
    windows.record(9.0)
    windows.record(9.0)
    assert windows.snapshot() == ((9.0, 9.0),)


def test_stream_cost_snapshot_is_immutable() -> None:
    snapshot = CacheCore().stream_cost_snapshot("db")
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.stream_polls = 99  # type: ignore[misc]


def test_stream_cost_snapshot_only_exposes_safe_primitive_fields() -> None:
    core = CacheCore(
        CacheCoreConfig(
            lag_capture_window_config=LagCaptureWindowConfig(
                window_count=1, events_per_window=1, min_separation_events=0
            )
        )
    )
    core.record_stream_poll("db")
    core.record_logical_event_bytes("db", 128)
    core.record_invalidation_applied("db", -0.01, 1.0, 2.0)
    snapshot = core.stream_cost_snapshot("db")

    for field in dataclasses.fields(snapshot):
        value = getattr(snapshot, field.name)
        assert isinstance(value, (str, int, tuple))
    for window in snapshot.invalidation_lag_windows:
        assert isinstance(window, tuple)
        for sample in window:
            assert isinstance(sample, float)
    for reading in snapshot.invalidation_apply_readings:
        assert isinstance(reading, InvalidationApplyReading)
        assert isinstance(reading.wall_seconds, float)
        assert isinstance(reading.monotonic_seconds, float)


def test_stream_cost_snapshot_labels_resident_bytes_scope_and_lag_clock_skew() -> None:
    core = CacheCore()
    snapshot = core.stream_cost_snapshot("db")

    assert snapshot.resident_bytes_scope
    assert snapshot.invalidation_lag_clock_skew_limitation
    assert snapshot.resident_bytes == core.snapshot().used_bytes


def test_stream_cost_snapshot_tracks_polls_bytes_and_invalidations() -> None:
    core = CacheCore()
    core.record_stream_poll("db")
    core.record_stream_poll("db")
    core.record_logical_event_bytes("db", 10)
    core.record_logical_event_bytes("db", 20)
    core.record_invalidation_applied("db", 0.5, 1.0, 2.0)

    snapshot = core.stream_cost_snapshot("db")

    assert snapshot.stream_polls == 2
    assert snapshot.logical_event_bytes == 30
    assert snapshot.invalidations == 1
    assert snapshot.invalidation_lag_windows == ()
    assert snapshot.invalidation_apply_readings == (
        InvalidationApplyReading(wall_seconds=1.0, monotonic_seconds=2.0),
    )


def test_invalidation_apply_readings_exclude_separator_events() -> None:
    core = CacheCore(
        CacheCoreConfig(
            lag_capture_window_config=LagCaptureWindowConfig(
                window_count=2, events_per_window=1, min_separation_events=1
            )
        )
    )
    core.record_invalidation_applied("db", 1.0, 1.0, 2.0)
    core.record_invalidation_applied("db", 2.0, 3.0, 4.0)
    core.record_invalidation_applied("db", 3.0, 5.0, 6.0)

    snapshot = core.stream_cost_snapshot("db")

    assert snapshot.invalidations == 3
    assert snapshot.invalidation_apply_readings == (
        InvalidationApplyReading(wall_seconds=1.0, monotonic_seconds=2.0),
        InvalidationApplyReading(wall_seconds=5.0, monotonic_seconds=6.0),
    )


def test_stream_cost_is_scoped_per_database_stream() -> None:
    core = CacheCore()
    core.record_stream_poll("db_one")
    core.record_invalidation_applied("db_two", 1.0, 1.0, 2.0)

    assert core.stream_cost_snapshot("db_one").stream_polls == 1
    assert core.stream_cost_snapshot("db_one").invalidations == 0
    assert core.stream_cost_snapshot("db_two").stream_polls == 0
    assert core.stream_cost_snapshot("db_two").invalidations == 1
    assert set(core.active_stream_cost_databases()) == {"db_one", "db_two"}


def test_stream_cost_snapshot_does_not_register_an_untouched_database() -> None:
    core = CacheCore()

    core.stream_cost_snapshot("db")

    assert core.active_stream_cost_databases() == []


def test_reset_stream_cost_statistics_on_an_untouched_database_is_a_no_op() -> None:
    core = CacheCore()

    core.reset_stream_cost_statistics("db")

    assert core.active_stream_cost_databases() == []
    assert core.stream_cost_snapshot("db").stream_polls == 0


def test_reset_stream_cost_statistics_scopes_to_one_database_by_default() -> None:
    core = CacheCore()
    core.record_stream_poll("db_one")
    core.record_stream_poll("db_two")

    core.reset_stream_cost_statistics("db_one")

    assert core.stream_cost_snapshot("db_one").stream_polls == 0
    assert core.stream_cost_snapshot("db_two").stream_polls == 1


def test_reset_stream_cost_statistics_never_interleaves_with_an_in_flight_record() -> (
    None
):
    core = CacheCore(
        CacheCoreConfig(
            lag_capture_window_config=LagCaptureWindowConfig(
                window_count=1, events_per_window=1, min_separation_events=0
            )
        )
    )
    barrier = threading.Barrier(2)

    def _record() -> None:
        barrier.wait()
        core.record_invalidation_applied("db", 1.0, 1.0, 2.0)

    def _reset() -> None:
        barrier.wait()
        core.reset_stream_cost_statistics("db")

    for _ in range(200):
        core.reset_stream_cost_statistics("db")
        with ThreadPoolExecutor(max_workers=2) as pool:
            record_future = pool.submit(_record)
            reset_future = pool.submit(_reset)
            record_future.result()
            reset_future.result()

        snapshot = core.stream_cost_snapshot("db")
        recorded_lag_samples = sum(
            len(window) for window in snapshot.invalidation_lag_windows
        )
        assert (snapshot.invalidations == 1) == (recorded_lag_samples == 1)
        assert snapshot.invalidations in {0, 1}
        assert recorded_lag_samples in {0, 1}
        assert len(snapshot.invalidation_apply_readings) == recorded_lag_samples


def test_reset_stream_cost_statistics_without_a_database_resets_every_stream() -> None:
    core = CacheCore()
    core.record_stream_poll("db_one")
    core.record_stream_poll("db_two")

    core.reset_stream_cost_statistics()

    assert core.stream_cost_snapshot("db_one").stream_polls == 0
    assert core.stream_cost_snapshot("db_two").stream_polls == 0


def test_oversized_admission_increments_only_the_oversized_bypass_counter() -> None:
    core = CacheCore(CacheCoreConfig(shared_budget_bytes=1024, max_entry_bytes=32))
    namespace = NamespaceId("db", "coll")
    capture = core.begin_identity_admission(namespace, "doc-1")

    core.admit_identity(capture, "full", {"v": "x" * 200})

    snapshot = core.snapshot()
    assert snapshot.oversized_bypasses == 1
    assert snapshot.bypasses == 0


def test_unavailable_database_bypass_does_not_touch_oversized_counter(
    namespace: NamespaceId,
) -> None:
    core = CacheCore()
    core.set_database_available(namespace.database, available=False)

    core.lookup_identity(namespace, "doc-1", "full")

    snapshot = core.snapshot()
    assert snapshot.bypasses == 1
    assert snapshot.oversized_bypasses == 0


def test_uncached_namespace_write_event_records_no_invalidation_or_lag() -> None:
    core = CacheCore()
    event = {
        "operationType": "insert",
        "ns": {"db": "db", "coll": "coll"},
        "documentKey": {"_id": "doc-1"},
        "wallTime": _WALL_TIME,
    }

    route_change_event(core, "db", event)

    snapshot = core.stream_cost_snapshot("db")
    assert snapshot.invalidations == 0
    assert snapshot.invalidation_lag_windows == ()


def test_cached_namespace_write_event_records_signed_invalidation_lag() -> None:
    core = CacheCore(
        CacheCoreConfig(
            lag_capture_window_config=LagCaptureWindowConfig(
                window_count=1, events_per_window=1, min_separation_events=0
            )
        )
    )
    namespace = NamespaceId("db", "coll")
    capture = core.begin_identity_admission(namespace, "doc-1")
    core.admit_identity(capture, "full", {"v": 1})
    future_wall_time = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)
    event = {
        "operationType": "insert",
        "ns": {"db": "db", "coll": "coll"},
        "documentKey": {"_id": "doc-1"},
        "wallTime": future_wall_time,
    }

    route_change_event(core, "db", event)

    snapshot = core.stream_cost_snapshot("db")
    assert snapshot.invalidations == 1
    ((sample,),) = snapshot.invalidation_lag_windows
    assert sample < 0


def test_cached_namespace_write_event_handles_datetime_ms_wall_time() -> None:
    core = CacheCore(
        CacheCoreConfig(
            lag_capture_window_config=LagCaptureWindowConfig(
                window_count=1, events_per_window=1, min_separation_events=0
            )
        )
    )
    namespace = NamespaceId("db", "coll")
    capture = core.begin_identity_admission(namespace, "doc-1")
    core.admit_identity(capture, "full", {"v": 1})
    future_wall_time = DatetimeMS(
        int(
            (
                datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)
            ).timestamp()
            * 1000
        )
    )
    event = {
        "operationType": "insert",
        "ns": {"db": "db", "coll": "coll"},
        "documentKey": {"_id": "doc-1"},
        "wallTime": future_wall_time,
    }

    route_change_event(core, "db", event)

    snapshot = core.stream_cost_snapshot("db")
    assert snapshot.invalidations == 1
    ((sample,),) = snapshot.invalidation_lag_windows
    assert sample < 0


def test_invalidate_event_clearing_several_namespaces_records_one_lag_sample() -> None:
    core = CacheCore()
    first = NamespaceId("db", "first")
    second = NamespaceId("db", "second")
    for namespace in (first, second):
        capture = core.capture_namespace_generation(namespace)
        core.admit_namespace(capture, "query", [1])
    event = {"operationType": "invalidate", "wallTime": _WALL_TIME}

    route_change_event(core, "db", event)

    snapshot = core.stream_cost_snapshot("db")
    assert snapshot.invalidations == 1


def test_rename_event_touching_both_namespaces_records_one_lag_sample() -> None:
    core = CacheCore()
    source = NamespaceId("db", "old_coll")
    destination = NamespaceId("db", "new_coll")
    for namespace in (source, destination):
        capture = core.capture_namespace_generation(namespace)
        core.admit_namespace(capture, "query", [1])
    event = {
        "operationType": "rename",
        "ns": {"db": "db", "coll": "old_coll"},
        "to": {"db": "db", "coll": "new_coll"},
        "wallTime": _WALL_TIME,
    }

    route_change_event(core, "db", event)

    snapshot = core.stream_cost_snapshot("db")
    assert snapshot.invalidations == 1


def test_stream_cost_snapshot_never_carries_document_or_resume_token_content() -> None:
    core = CacheCore()
    namespace = NamespaceId("db", "coll")
    capture = core.begin_identity_admission(namespace, "doc-1")
    core.admit_identity(
        capture,
        "full",
        {"secret_field": "sensitive-account-secret"},  # pragma: allowlist secret
    )
    event = {
        "operationType": "insert",
        "ns": {"db": "db", "coll": "coll"},
        "documentKey": {"_id": "resume-token-abc123"},
        "wallTime": _WALL_TIME,
    }

    route_change_event(core, "db", event)

    snapshot = core.stream_cost_snapshot("db")
    rendered = str(dataclasses.astuple(snapshot))
    assert "sensitive-account-secret" not in rendered
    assert "resume-token-abc123" not in rendered
