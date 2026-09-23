from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import pytest

from benchmarks.stream_cost.calibration import (
    CalibrationPoint,
    CalibrationSeries,
    ClockSample,
    PairedReading,
    PeriodicCalibrationSampler,
    TopologyChangeListener,
    delta_margin_seconds,
    drift_adjusted_delta_seconds,
    host_clock_stepped,
    is_not_meaningfully_worse,
    meets_absolute_threshold,
    sample_clock_offset,
    validate_cadence,
)
from benchmarks.stream_cost.errors import BenchmarkConfigurationError

if TYPE_CHECKING:
    from collections.abc import Callable

    from pymongo.monitoring import (
        TopologyClosedEvent,
        TopologyDescriptionChangedEvent,
        TopologyOpenedEvent,
    )

pytestmark = pytest.mark.unit


def _sequence_source(values: list[float]) -> Callable[[], float]:
    iterator = iter(values)
    return lambda: next(iterator)


def test_clock_sample_rejects_backwards_wall_time() -> None:
    with pytest.raises(BenchmarkConfigurationError, match="must not precede"):
        ClockSample(
            wall_t0=1.0,
            wall_t1=0.5,
            monotonic_t0=0.0,
            monotonic_t1=0.5,
            server_time_seconds=1.0,
            election_id=None,
        )


def test_sample_clock_offset_rejects_non_positive_rounds() -> None:
    with pytest.raises(BenchmarkConfigurationError, match="rounds must be positive"):
        sample_clock_offset(dict, rounds=0)


def test_sample_clock_offset_computes_offset_and_uncertainty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "benchmarks.stream_cost.calibration.time.time", _sequence_source([100.0, 100.2])
    )
    monkeypatch.setattr(
        "benchmarks.stream_cost.calibration.time.monotonic",
        _sequence_source([1.0, 1.2]),
    )
    server_time = datetime(2024, 1, 1, tzinfo=UTC)

    def send_hello() -> dict[str, object]:
        return {
            "localTime": server_time,
            "electionId": "election-1",
            "isWritablePrimary": True,
        }

    point = sample_clock_offset(send_hello, rounds=1)
    expected_offset = server_time.timestamp() - (100.0 + 100.2) / 2
    assert point.selected.offset_seconds == pytest.approx(expected_offset)
    assert point.selected.uncertainty_seconds == pytest.approx(0.2 / 2 + 0.001)


def test_sample_clock_offset_treats_naive_datetime_as_utc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "benchmarks.stream_cost.calibration.time.time", _sequence_source([0.0, 0.0])
    )
    monkeypatch.setattr(
        "benchmarks.stream_cost.calibration.time.monotonic",
        _sequence_source([0.0, 0.0]),
    )
    naive_time = datetime(2024, 1, 1)  # noqa: DTZ001
    aware_time = naive_time.replace(tzinfo=UTC)

    point = sample_clock_offset(
        lambda: {
            "localTime": naive_time,
            "electionId": "election-1",
            "isWritablePrimary": True,
        },
        rounds=1,
    )
    assert point.selected.offset_seconds == pytest.approx(aware_time.timestamp())


def test_sample_clock_offset_selects_minimum_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "benchmarks.stream_cost.calibration.time.time",
        _sequence_source([100.0, 100.5, 200.0, 200.05, 300.0, 300.3]),
    )
    monkeypatch.setattr(
        "benchmarks.stream_cost.calibration.time.monotonic",
        _sequence_source([1000.0, 1000.5, 2000.0, 2000.05, 3000.0, 3000.3]),
    )
    responses = iter(
        [
            {
                "localTime": datetime(2024, 1, 1, tzinfo=UTC),
                "electionId": "a",
                "isWritablePrimary": True,
            },
            {
                "localTime": datetime(2024, 1, 2, tzinfo=UTC),
                "electionId": "b",
                "isWritablePrimary": True,
            },
            {
                "localTime": datetime(2024, 1, 3, tzinfo=UTC),
                "electionId": "c",
                "isWritablePrimary": True,
            },
        ]
    )

    point = sample_clock_offset(lambda: next(responses), rounds=3)
    assert point.selected.election_id == "b"
    assert point.selected.round_trip_seconds == pytest.approx(0.05)
    assert [sample.election_id for sample in point.rounds] == ["a", "b", "c"]


def test_sample_clock_offset_retains_every_round_not_just_the_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "benchmarks.stream_cost.calibration.time.time",
        _sequence_source([100.0, 100.5, 200.0, 200.05]),
    )
    monkeypatch.setattr(
        "benchmarks.stream_cost.calibration.time.monotonic",
        _sequence_source([1000.0, 1000.5, 2000.0, 2000.05]),
    )
    responses = iter(
        [
            {
                "localTime": datetime(2024, 1, 1, tzinfo=UTC),
                "electionId": "a",
                "isWritablePrimary": True,
            },
            {
                "localTime": datetime(2024, 1, 2, tzinfo=UTC),
                "electionId": "b",
                "isWritablePrimary": True,
            },
        ]
    )

    point = sample_clock_offset(lambda: next(responses), rounds=2)
    assert point.selected.election_id == "b"
    assert len(point.rounds) == 2
    assert point.rounds[0].election_id == "a"


def test_sample_clock_offset_rejects_a_response_not_from_the_primary() -> None:
    def send_hello() -> dict[str, object]:
        return {
            "localTime": datetime(2024, 1, 1, tzinfo=UTC),
            "electionId": "a",
            "isWritablePrimary": False,
        }

    with pytest.raises(
        BenchmarkConfigurationError, match="not from a writable primary"
    ):
        sample_clock_offset(send_hello, rounds=1)


def test_sample_clock_offset_rejects_a_response_missing_election_id() -> None:
    def send_hello() -> dict[str, object]:
        return {
            "localTime": datetime(2024, 1, 1, tzinfo=UTC),
            "electionId": None,
            "isWritablePrimary": True,
        }

    with pytest.raises(BenchmarkConfigurationError, match="missing electionId"):
        sample_clock_offset(send_hello, rounds=1)


def _clock_sample(
    *, round_trip: float, offset: float, election_id: object = None
) -> ClockSample:
    wall_t0 = 0.0
    wall_t1 = round_trip
    mid = (wall_t0 + wall_t1) / 2
    return ClockSample(
        wall_t0=wall_t0,
        wall_t1=wall_t1,
        monotonic_t0=0.0,
        monotonic_t1=round_trip,
        server_time_seconds=mid + offset,
        election_id=election_id,
    )


def _point(
    *, round_trip: float = 0.1, offset: float = 10.0, election_id: object = None
) -> CalibrationPoint:
    sample = _clock_sample(
        round_trip=round_trip, offset=offset, election_id=election_id
    )
    return CalibrationPoint(selected=sample, rounds=(sample,))


def test_calibration_point_rejects_selected_outside_rounds() -> None:
    selected = _clock_sample(round_trip=0.1, offset=10.0)
    other = _clock_sample(round_trip=0.2, offset=20.0)
    with pytest.raises(
        BenchmarkConfigurationError, match="selected must be one of rounds"
    ):
        CalibrationPoint(selected=selected, rounds=(other,))


def test_calibration_point_rejects_empty_rounds() -> None:
    selected = _clock_sample(round_trip=0.1, offset=10.0)
    with pytest.raises(BenchmarkConfigurationError, match="at least one round"):
        CalibrationPoint(selected=selected, rounds=())


def test_calibration_series_rejects_empty_points() -> None:
    with pytest.raises(
        BenchmarkConfigurationError, match="at least one calibration point"
    ):
        CalibrationSeries(points=())


def test_calibration_series_total_uncertainty_with_single_sample() -> None:
    initial = _point(round_trip=0.1, offset=10.0)
    series = CalibrationSeries(points=(initial,))
    assert series.total_uncertainty_seconds == pytest.approx(
        initial.selected.uncertainty_seconds
    )


def test_calibration_series_total_uncertainty_dominated_by_drift() -> None:
    initial = _point(round_trip=0.1, offset=10.0)
    drifted = _point(round_trip=0.2, offset=10.5)
    series = CalibrationSeries(points=(initial, drifted))
    drift = series.drift_seconds(drifted.selected)
    assert drift == pytest.approx(0.5)
    combined_uncertainty = series.combined_drift_uncertainty_seconds(drifted.selected)
    assert combined_uncertainty == pytest.approx(
        initial.selected.uncertainty_seconds + drifted.selected.uncertainty_seconds
    )
    assert series.total_uncertainty_seconds == pytest.approx(
        drift + combined_uncertainty
    )


@pytest.mark.parametrize(
    ("tolerance", "expected"),
    [
        (0.4, True),
        (0.6, False),
    ],
)
def test_calibration_series_exceeds_drift_tolerance(
    tolerance: float, expected: bool
) -> None:
    initial = _point(round_trip=0.1, offset=10.0)
    drifted = _point(round_trip=0.1, offset=10.5)
    series = CalibrationSeries(points=(initial, drifted))
    assert series.exceeds_drift_tolerance(tolerance) is expected


@pytest.mark.parametrize(
    ("election_ids", "expected"),
    [
        (("a", "a"), False),
        (("a", "b"), True),
        ((None, None), False),
        ((None, "a"), True),
        (("a", "b", "a"), True),
    ],
)
def test_calibration_series_has_election_change(
    election_ids: tuple[object, ...], expected: bool
) -> None:
    points = tuple(
        _point(round_trip=0.1, offset=10.0, election_id=election_id)
        for election_id in election_ids
    )
    series = CalibrationSeries(points=points)
    assert series.has_election_change is expected


def test_has_election_change_detects_change_in_a_discarded_round() -> None:
    winner = _clock_sample(round_trip=0.05, offset=10.0, election_id="a")
    loser = _clock_sample(round_trip=0.2, offset=10.0, election_id="b")
    point = CalibrationPoint(selected=winner, rounds=(loser, winner))
    series = CalibrationSeries(points=(point,))
    assert series.has_election_change is True


def _sample_with_readings(*, wall_t0: float, monotonic_t0: float) -> ClockSample:
    return ClockSample(
        wall_t0=wall_t0,
        wall_t1=wall_t0 + 0.1,
        monotonic_t0=monotonic_t0,
        monotonic_t1=monotonic_t0 + 0.1,
        server_time_seconds=wall_t0 + 0.05 + 10.0,
        election_id=None,
    )


def _point_with_readings(*, wall_t0: float, monotonic_t0: float) -> CalibrationPoint:
    sample = _sample_with_readings(wall_t0=wall_t0, monotonic_t0=monotonic_t0)
    return CalibrationPoint(selected=sample, rounds=(sample,))


@pytest.mark.parametrize(
    ("second_wall_t0", "second_monotonic_t0", "tolerance", "expected"),
    [
        (100.0, 100.0, 0.05, False),
        (100.2, 100.0, 0.05, True),
        (100.02, 100.0, 0.05, False),
    ],
)
def test_calibration_series_has_host_clock_step(
    second_wall_t0: float, second_monotonic_t0: float, tolerance: float, expected: bool
) -> None:
    initial = _point_with_readings(wall_t0=0.0, monotonic_t0=0.0)
    second = _point_with_readings(
        wall_t0=second_wall_t0, monotonic_t0=second_monotonic_t0
    )
    series = CalibrationSeries(points=(initial, second))
    assert series.has_host_clock_step(tolerance_seconds=tolerance) is expected


def test_calibration_series_has_host_clock_step_detects_within_sample_step() -> None:
    stepped_sample = ClockSample(
        wall_t0=0.0,
        wall_t1=0.5,
        monotonic_t0=0.0,
        monotonic_t1=0.1,
        server_time_seconds=0.25,
        election_id=None,
    )
    point = CalibrationPoint(selected=stepped_sample, rounds=(stepped_sample,))
    series = CalibrationSeries(points=(point,))
    assert series.has_host_clock_step(tolerance_seconds=0.05) is True


def test_has_host_clock_step_detects_step_in_a_discarded_round() -> None:
    good_sample = _sample_with_readings(wall_t0=0.0, monotonic_t0=0.0)
    stepped_sample = ClockSample(
        wall_t0=1.0,
        wall_t1=1.5,
        monotonic_t0=1.0,
        monotonic_t1=1.1,
        server_time_seconds=1.25,
        election_id=None,
    )
    point = CalibrationPoint(selected=good_sample, rounds=(stepped_sample, good_sample))
    series = CalibrationSeries(points=(point,))
    assert series.has_host_clock_step(tolerance_seconds=0.05) is True


@pytest.mark.parametrize(
    ("cadence", "threshold", "should_raise"),
    [
        (1.0, 10.0, False),
        (1.0, 10.01, False),
        (2.0, 10.0, True),
    ],
)
def test_validate_cadence(cadence: float, threshold: float, should_raise: bool) -> None:
    if should_raise:
        with pytest.raises(BenchmarkConfigurationError, match="exceeds"):
            validate_cadence(cadence, threshold)
    else:
        validate_cadence(cadence, threshold)


@pytest.mark.parametrize(
    ("cadence", "threshold", "max_fraction", "match"),
    [
        (-1.0, 10.0, 0.1, "cadence_seconds"),
        (float("nan"), 10.0, 0.1, "cadence_seconds"),
        (0.0, 10.0, 0.1, "cadence_seconds"),
        (1.0, -10.0, 0.1, "threshold_seconds"),
        (1.0, float("nan"), 0.1, "threshold_seconds"),
        (1.0, 10.0, -0.1, "max_fraction"),
        (1.0, 10.0, float("nan"), "max_fraction"),
    ],
)
def test_validate_cadence_rejects_invalid_inputs(
    cadence: float, threshold: float, max_fraction: float, match: str
) -> None:
    with pytest.raises(BenchmarkConfigurationError, match=match):
        validate_cadence(cadence, threshold, max_fraction=max_fraction)


@pytest.mark.parametrize(
    ("wall_elapsed", "monotonic_elapsed", "tolerance", "expected"),
    [
        (10.0, 10.0, 0.1, False),
        (10.2, 10.0, 0.1, True),
        (10.05, 10.0, 0.1, False),
    ],
)
def test_host_clock_stepped(
    wall_elapsed: float, monotonic_elapsed: float, tolerance: float, expected: bool
) -> None:
    first = PairedReading(wall_seconds=0.0, monotonic_seconds=0.0)
    second = PairedReading(
        wall_seconds=wall_elapsed, monotonic_seconds=monotonic_elapsed
    )
    assert host_clock_stepped(first, second, tolerance_seconds=tolerance) is expected


@pytest.mark.parametrize(
    ("value", "uncertainty", "threshold", "expected"),
    [
        (1.0, 0.1, 1.1, True),
        (1.0, 0.2, 1.1, False),
        (1.0, 0.1, 1.09, False),
    ],
)
def test_meets_absolute_threshold(
    value: float, uncertainty: float, threshold: float, expected: bool
) -> None:
    assert meets_absolute_threshold(value, uncertainty, threshold) is expected


def test_delta_margin_seconds_doubles_uncertainty() -> None:
    assert delta_margin_seconds(0.25) == pytest.approx(0.5)


def test_drift_adjusted_delta_seconds_adds_margin() -> None:
    delta = drift_adjusted_delta_seconds(1.0, 1.5, 0.1)
    assert delta == pytest.approx((1.5 - 1.0) + 2 * 0.1)


@pytest.mark.parametrize(
    ("control", "loaded", "uncertainty", "threshold", "expected"),
    [
        (1.0, 1.05, 0.01, 0.1, True),
        (1.0, 1.5, 0.01, 0.1, False),
    ],
)
def test_is_not_meaningfully_worse(
    control: float, loaded: float, uncertainty: float, threshold: float, expected: bool
) -> None:
    assert (
        is_not_meaningfully_worse(control, loaded, uncertainty, threshold) is expected
    )


@dataclass(frozen=True, slots=True)
class _FakeServerDescription:
    is_writable: bool


@dataclass(frozen=True, slots=True)
class _FakeTopologyDescription:
    servers: dict[tuple[str, int], _FakeServerDescription]

    def server_descriptions(self) -> dict[tuple[str, int], _FakeServerDescription]:
        return self.servers


@dataclass(frozen=True, slots=True)
class _FakeTopologyDescriptionChangedEvent:
    new_description: _FakeTopologyDescription


def _change_event(
    servers: dict[tuple[str, int], _FakeServerDescription],
) -> TopologyDescriptionChangedEvent:
    event = _FakeTopologyDescriptionChangedEvent(_FakeTopologyDescription(servers))
    return cast("TopologyDescriptionChangedEvent", event)


def test_topology_change_listener_starts_unchanged() -> None:
    listener = TopologyChangeListener()
    assert bool(listener.primary_changed) is False
    listener.opened(cast("TopologyOpenedEvent", object()))
    listener.closed(cast("TopologyClosedEvent", object()))
    assert bool(listener.primary_changed) is False


def test_topology_change_listener_ignores_no_writable_primary() -> None:
    listener = TopologyChangeListener()
    event = _change_event({("host", 1): _FakeServerDescription(is_writable=False)})
    listener.description_changed(event)
    assert bool(listener.primary_changed) is False


def test_topology_change_listener_detects_primary_change() -> None:
    listener = TopologyChangeListener()
    first_event = _change_event({("host", 1): _FakeServerDescription(is_writable=True)})
    listener.description_changed(first_event)
    assert bool(listener.primary_changed) is False

    same_primary_event = _change_event(
        {("host", 1): _FakeServerDescription(is_writable=True)}
    )
    listener.description_changed(same_primary_event)
    assert bool(listener.primary_changed) is False

    new_primary_event = _change_event(
        {("host", 2): _FakeServerDescription(is_writable=True)}
    )
    listener.description_changed(new_primary_event)
    assert bool(listener.primary_changed) is True


def test_topology_change_listener_flags_primary_loss_immediately() -> None:
    listener = TopologyChangeListener()
    primary_event = _change_event(
        {("host", 1): _FakeServerDescription(is_writable=True)}
    )
    listener.description_changed(primary_event)
    assert bool(listener.primary_changed) is False

    no_primary_event = _change_event(
        {("host", 1): _FakeServerDescription(is_writable=False)}
    )
    listener.description_changed(no_primary_event)
    assert bool(listener.primary_changed)

    same_primary_returns_event = _change_event(
        {("host", 1): _FakeServerDescription(is_writable=True)}
    )
    listener.description_changed(same_primary_returns_event)
    assert bool(listener.primary_changed)


def _stub_send_hello() -> dict[str, object]:
    return {
        "localTime": datetime(2024, 1, 1, tzinfo=UTC),
        "electionId": "election-1",
        "isWritablePrimary": True,
    }


def test_periodic_calibration_sampler_rejects_non_positive_cadence() -> None:
    with pytest.raises(BenchmarkConfigurationError, match="cadence_seconds"):
        PeriodicCalibrationSampler(_stub_send_hello, cadence_seconds=0.0, rounds=1)


def test_periodic_calibration_sampler_stop_without_start_returns_no_points() -> None:
    sampler = PeriodicCalibrationSampler(
        _stub_send_hello, cadence_seconds=10.0, rounds=1
    )
    assert sampler.stop() == ()


def test_periodic_calibration_sampler_rejects_a_second_start() -> None:
    sampler = PeriodicCalibrationSampler(
        _stub_send_hello, cadence_seconds=10.0, rounds=1
    )
    sampler.start()
    try:
        with pytest.raises(BenchmarkConfigurationError, match="already been started"):
            sampler.start()
    finally:
        sampler.stop()


def test_periodic_calibration_sampler_sample_now_appends_a_point() -> None:
    sampler = PeriodicCalibrationSampler(
        _stub_send_hello, cadence_seconds=10.0, rounds=1
    )
    point = sampler.sample_now()  # pytriage: TR5 (must run before points() below)
    assert sampler.points() == (point,)


def test_periodic_calibration_sampler_samples_repeatedly_at_the_cadence() -> None:
    sampler = PeriodicCalibrationSampler(
        _stub_send_hello, cadence_seconds=0.02, rounds=1
    )
    sampler.start()
    time.sleep(0.15)
    minimum_expected_points = 3
    assert len(sampler.stop()) >= minimum_expected_points
