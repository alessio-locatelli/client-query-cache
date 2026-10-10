from __future__ import annotations

import dataclasses
import datetime
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, get_type_hints

import pytest
from bson.datetime_ms import DatetimeMS
from hypothesis import given
from hypothesis import strategies as st

from client_query_cache._core.errors import CacheConfigurationError
from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.manager import CacheCore, CacheCoreConfig
from client_query_cache._core.stream_cost import (
    InvalidationApplyReading,
    LagCaptureWindowConfig,
    LagCaptureWindows,
)
from client_query_cache._core.stream_events import route_change_event
from client_query_cache._types import BsonDict, NonNegativeInt

if TYPE_CHECKING:
    from collections.abc import Callable

pytestmark = pytest.mark.unit

_WALL_TIME = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
_LAG_CONFIG_HINTS = get_type_hints(LagCaptureWindowConfig, include_extras=True)


@pytest.fixture
def single_sample_core() -> CacheCore:
    return CacheCore(
        CacheCoreConfig(
            lag_capture_window_config=LagCaptureWindowConfig(
                window_count=1, events_per_window=1, min_separation_events=0
            )
        )
    )


def _insert_event(wall_time: object, document_id: str = "doc-1") -> BsonDict:
    return {
        "operationType": "insert",
        "ns": {"db": "db", "coll": "coll"},
        "documentKey": {"_id": document_id},
        "wallTime": wall_time,
    }


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


@given(
    st.fixed_dictionaries(
        {name: st.from_type(hint) for name, hint in _LAG_CONFIG_HINTS.items()}
    )
)
def test_lag_capture_window_config_accepts_every_annotated_value(
    kwargs: dict[str, NonNegativeInt],
) -> None:
    assert dataclasses.asdict(LagCaptureWindowConfig(**kwargs)) == kwargs


@pytest.mark.parametrize(
    ("config", "recorded", "expected"),
    [
        pytest.param(
            LagCaptureWindowConfig(
                window_count=2, events_per_window=3, min_separation_events=0
            ),
            tuple(float(value) for value in range(9)),
            ((3.0, 4.0, 5.0), (6.0, 7.0, 8.0)),
            id="fixed_contiguous_gap_free_blocks",
        ),
        pytest.param(
            LagCaptureWindowConfig(
                window_count=1, events_per_window=2, min_separation_events=0
            ),
            (0.0, 1.0, 2.0),
            ((0.0, 1.0),),
            id="completed_window_kept_until_a_replacement_fills",
        ),
        pytest.param(
            LagCaptureWindowConfig(
                window_count=2, events_per_window=2, min_separation_events=2
            ),
            tuple(float(value) for value in range(8)),
            ((0.0, 1.0), (4.0, 5.0)),
            id="minimum_separation_between_windows",
        ),
        pytest.param(
            LagCaptureWindowConfig(
                window_count=1, events_per_window=2, min_separation_events=0
            ),
            (-0.25, -1.5),
            ((-0.25, -1.5),),
            id="signed_values_without_clamping",
        ),
    ],
)
def test_lag_capture_windows_snapshot(
    config: LagCaptureWindowConfig,
    recorded: tuple[float, ...],
    expected: tuple[tuple[float, ...], ...],
) -> None:
    windows = LagCaptureWindows(config)

    for value in recorded:
        windows.record(value)

    assert windows.snapshot() == expected


def test_lag_capture_windows_stays_within_its_configured_memory_bound() -> None:
    config = LagCaptureWindowConfig(
        window_count=3, events_per_window=10, min_separation_events=0
    )
    windows = LagCaptureWindows(config)

    for value in range(10_000):
        windows.record(float(value))
        assert len(windows._windows) <= config.window_count
        assert len(windows._current) < config.events_per_window

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


def test_stream_cost_snapshot_only_exposes_safe_primitive_fields(
    single_sample_core: CacheCore,
) -> None:
    single_sample_core.record_stream_poll("db")
    single_sample_core.record_logical_event_bytes("db", 128)
    single_sample_core.record_invalidation_applied("db", -0.01, 1.0, 2.0)
    snapshot = single_sample_core.stream_cost_snapshot("db")

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


@pytest.mark.parametrize(
    ("reset_databases", "expected_db_two_polls"),
    [
        pytest.param(("db_one",), 1, id="named_database_only"),
        pytest.param((), 0, id="every_stream_without_a_database"),
    ],
)
def test_reset_stream_cost_statistics_scope(
    reset_databases: tuple[str, ...], expected_db_two_polls: NonNegativeInt
) -> None:
    core = CacheCore()
    core.record_stream_poll("db_one")
    core.record_stream_poll("db_two")

    core.reset_stream_cost_statistics(*reset_databases)

    assert core.stream_cost_snapshot("db_one").stream_polls == 0
    assert core.stream_cost_snapshot("db_two").stream_polls == expected_db_two_polls


def test_reset_stream_cost_statistics_never_interleaves_with_an_in_flight_record(
    single_sample_core: CacheCore,
) -> None:
    core = single_sample_core
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

    route_change_event(core, "db", _insert_event(_WALL_TIME))

    snapshot = core.stream_cost_snapshot("db")
    assert snapshot.invalidations == 0
    assert snapshot.invalidation_lag_windows == ()


@pytest.mark.parametrize(
    "to_wall_time",
    [
        pytest.param(lambda moment: moment, id="datetime"),
        pytest.param(DatetimeMS, id="datetime_ms"),
    ],
)
def test_cached_namespace_write_event_records_signed_invalidation_lag(
    single_sample_core: CacheCore,
    to_wall_time: Callable[[datetime.datetime], object],
) -> None:
    capture = single_sample_core.begin_identity_admission(
        NamespaceId("db", "coll"), "doc-1"
    )
    single_sample_core.admit_identity(capture, "full", {"v": 1})
    future_wall_time = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)

    route_change_event(
        single_sample_core, "db", _insert_event(to_wall_time(future_wall_time))
    )

    snapshot = single_sample_core.stream_cost_snapshot("db")
    assert snapshot.invalidations == 1
    ((sample,),) = snapshot.invalidation_lag_windows
    assert sample < 0


@pytest.mark.parametrize(
    ("collections", "event"),
    [
        pytest.param(
            ("first", "second"),
            {"operationType": "invalidate", "wallTime": _WALL_TIME},
            id="invalidate_clearing_several_namespaces",
        ),
        pytest.param(
            ("old_coll", "new_coll"),
            {
                "operationType": "rename",
                "ns": {"db": "db", "coll": "old_coll"},
                "to": {"db": "db", "coll": "new_coll"},
                "wallTime": _WALL_TIME,
            },
            id="rename_touching_both_namespaces",
        ),
    ],
)
def test_multi_namespace_event_records_one_lag_sample(
    collections: tuple[str, ...], event: BsonDict
) -> None:
    core = CacheCore()
    for collection in collections:
        capture = core.capture_namespace_generation(NamespaceId("db", collection))
        core.admit_namespace(capture, "query", [1])

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

    route_change_event(core, "db", _insert_event(_WALL_TIME, "resume-token-abc123"))

    snapshot = core.stream_cost_snapshot("db")
    rendered = str(dataclasses.astuple(snapshot))
    assert "sensitive-account-secret" not in rendered
    assert "resume-token-abc123" not in rendered
