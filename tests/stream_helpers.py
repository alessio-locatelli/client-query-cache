from client_query_cache._core.stream_cost import (
    LagCaptureWindowConfig,
    StreamCostSnapshot,
)

SINGLE_EVENT_LAG_WINDOW = LagCaptureWindowConfig(
    window_count=1, events_per_window=1, min_separation_events=0
)
WALL_TIME_BOUND_TOLERANCE_SECONDS = 1.0


def assert_lag_matches_write_interval(
    snapshot: StreamCostSnapshot, write_started: float, write_finished: float
) -> None:
    assert snapshot.invalidations == 1
    lag_seconds = snapshot.invalidation_lag_windows[0][0]
    applied_at = snapshot.invalidation_apply_readings[0].wall_seconds
    tolerance = WALL_TIME_BOUND_TOLERANCE_SECONDS
    assert (
        applied_at - write_finished - tolerance
        <= lag_seconds
        <= applied_at - write_started + tolerance
    )
