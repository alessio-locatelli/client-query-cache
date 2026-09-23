from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pymongo.monitoring import TopologyListener

from benchmarks.stream_cost.errors import (
    BenchmarkConfigurationError,
    BenchmarkSetupError,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from pymongo.monitoring import (
        TopologyClosedEvent,
        TopologyDescriptionChangedEvent,
        TopologyOpenedEvent,
    )
    from pymongo.topology_description import TopologyDescription

_QUANTIZATION_ALLOWANCE_SECONDS = 0.001


def _bson_datetime_to_epoch_seconds(value: datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.timestamp()


@dataclass(frozen=True, slots=True)
class ClockSample:
    wall_t0: float
    wall_t1: float
    monotonic_t0: float
    monotonic_t1: float
    server_time_seconds: float
    election_id: object | None

    def __post_init__(self) -> None:
        if self.wall_t1 < self.wall_t0:
            message = "wall_t1 must not precede wall_t0"
            raise BenchmarkConfigurationError(message)

    @property
    def round_trip_seconds(self) -> float:
        return self.wall_t1 - self.wall_t0

    @property
    def offset_seconds(self) -> float:
        return self.server_time_seconds - (self.wall_t0 + self.wall_t1) / 2

    @property
    def uncertainty_seconds(self) -> float:
        return self.round_trip_seconds / 2 + _QUANTIZATION_ALLOWANCE_SECONDS


@dataclass(frozen=True, slots=True)
class CalibrationPoint:
    selected: ClockSample
    rounds: tuple[ClockSample, ...]

    def __post_init__(self) -> None:
        if not self.rounds:
            message = "at least one round is required"
            raise BenchmarkConfigurationError(message)
        if self.selected not in self.rounds:
            message = "selected must be one of rounds"
            raise BenchmarkConfigurationError(message)


def sample_clock_offset(
    send_hello: Callable[[], Mapping[str, object]], *, rounds: int
) -> CalibrationPoint:
    if rounds <= 0:
        message = "rounds must be positive"
        raise BenchmarkConfigurationError(message)
    collected: list[ClockSample] = []
    best: ClockSample | None = None
    for _ in range(rounds):
        wall_t0 = time.time()
        monotonic_t0 = time.monotonic()
        response = send_hello()
        wall_t1 = time.time()
        monotonic_t1 = time.monotonic()
        if response.get("isWritablePrimary") is not True:
            message = "hello response is not from a writable primary"
            raise BenchmarkConfigurationError(message)
        election_id = response.get("electionId")
        if election_id is None:
            message = "hello response is missing electionId"
            raise BenchmarkConfigurationError(message)
        local_time = response["localTime"]
        assert isinstance(local_time, datetime)
        sample = ClockSample(
            wall_t0=wall_t0,
            wall_t1=wall_t1,
            monotonic_t0=monotonic_t0,
            monotonic_t1=monotonic_t1,
            server_time_seconds=_bson_datetime_to_epoch_seconds(local_time),
            election_id=election_id,
        )
        collected.append(sample)
        if best is None or sample.round_trip_seconds < best.round_trip_seconds:
            best = sample
    assert best is not None
    return CalibrationPoint(selected=best, rounds=tuple(collected))


@dataclass(frozen=True, slots=True)
class CalibrationSeries:
    points: tuple[CalibrationPoint, ...]

    def __post_init__(self) -> None:
        if not self.points:
            message = "at least one calibration point is required"
            raise BenchmarkConfigurationError(message)

    @property
    def initial(self) -> ClockSample:
        return self.points[0].selected

    @property
    def _all_rounds(self) -> list[ClockSample]:
        return [sample for point in self.points for sample in point.rounds]

    def drift_seconds(self, sample: ClockSample) -> float:
        return abs(sample.offset_seconds - self.initial.offset_seconds)

    def combined_drift_uncertainty_seconds(self, sample: ClockSample) -> float:
        return self.initial.uncertainty_seconds + sample.uncertainty_seconds

    @property
    def total_uncertainty_seconds(self) -> float:
        selected = [point.selected for point in self.points]
        candidates = [self.initial.uncertainty_seconds]
        candidates.extend(
            self.drift_seconds(sample) + self.combined_drift_uncertainty_seconds(sample)
            for sample in selected[1:]
        )
        return max(candidates)

    def exceeds_drift_tolerance(self, tolerance_seconds: float) -> bool:
        selected = [point.selected for point in self.points]
        return any(
            self.drift_seconds(sample) > tolerance_seconds for sample in selected[1:]
        )

    @property
    def has_election_change(self) -> bool:
        election_ids = {sample.election_id for sample in self._all_rounds}
        return len(election_ids) > 1

    def has_host_clock_step(self, *, tolerance_seconds: float) -> bool:
        all_rounds = self._all_rounds
        for sample in all_rounds:
            sample_t0 = PairedReading(
                wall_seconds=sample.wall_t0, monotonic_seconds=sample.monotonic_t0
            )
            sample_t1 = PairedReading(
                wall_seconds=sample.wall_t1, monotonic_seconds=sample.monotonic_t1
            )
            if host_clock_stepped(
                sample_t0, sample_t1, tolerance_seconds=tolerance_seconds
            ):
                return True
        initial_reading = PairedReading(
            wall_seconds=self.initial.wall_t0,
            monotonic_seconds=self.initial.monotonic_t0,
        )
        return any(
            host_clock_stepped(
                initial_reading,
                PairedReading(
                    wall_seconds=sample.wall_t0, monotonic_seconds=sample.monotonic_t0
                ),
                tolerance_seconds=tolerance_seconds,
            )
            for sample in all_rounds
        )


def validate_cadence(
    cadence_seconds: float, threshold_seconds: float, *, max_fraction: float = 0.1
) -> None:
    if not math.isfinite(cadence_seconds) or cadence_seconds <= 0:
        message = "cadence_seconds must be a positive, finite number"
        raise BenchmarkConfigurationError(message)
    if not math.isfinite(threshold_seconds) or threshold_seconds <= 0:
        message = "threshold_seconds must be a positive, finite number"
        raise BenchmarkConfigurationError(message)
    if not math.isfinite(max_fraction) or max_fraction <= 0:
        message = "max_fraction must be a positive, finite number"
        raise BenchmarkConfigurationError(message)
    if cadence_seconds > threshold_seconds * max_fraction:
        message = (
            f"calibration cadence ({cadence_seconds}s) exceeds "
            f"{max_fraction:.0%} of the acceptable-lag threshold ({threshold_seconds}s)"
        )
        raise BenchmarkConfigurationError(message)


@dataclass(frozen=True, slots=True)
class PairedReading:
    wall_seconds: float
    monotonic_seconds: float


def host_clock_stepped(
    first: PairedReading, second: PairedReading, *, tolerance_seconds: float
) -> bool:
    wall_elapsed = second.wall_seconds - first.wall_seconds
    monotonic_elapsed = second.monotonic_seconds - first.monotonic_seconds
    return abs(wall_elapsed - monotonic_elapsed) > tolerance_seconds


def meets_absolute_threshold(
    value_seconds: float, total_uncertainty_seconds: float, threshold_seconds: float
) -> bool:
    return value_seconds + total_uncertainty_seconds <= threshold_seconds


def delta_margin_seconds(total_uncertainty_seconds: float) -> float:
    return 2 * total_uncertainty_seconds


def drift_adjusted_delta_seconds(
    control_percentile_seconds: float,
    loaded_percentile_seconds: float,
    total_uncertainty_seconds: float,
) -> float:
    raw_delta = loaded_percentile_seconds - control_percentile_seconds
    return raw_delta + delta_margin_seconds(total_uncertainty_seconds)


def is_not_meaningfully_worse(
    control_percentile_seconds: float,
    loaded_percentile_seconds: float,
    total_uncertainty_seconds: float,
    threshold_seconds: float,
) -> bool:
    adjusted_delta = drift_adjusted_delta_seconds(
        control_percentile_seconds, loaded_percentile_seconds, total_uncertainty_seconds
    )
    return adjusted_delta <= threshold_seconds


def _writable_primary_address(
    description: TopologyDescription,
) -> tuple[str, int | None] | None:
    for address, server in description.server_descriptions().items():
        if server.is_writable:
            return address
    return None


class TopologyChangeListener(TopologyListener):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current_primary: tuple[str, int | None] | None = None
        self._primary_changed = False

    @property
    def primary_changed(self) -> bool:
        with self._lock:
            return self._primary_changed

    def reset(self) -> None:
        with self._lock:
            self._primary_changed = False
            self._current_primary = None

    @staticmethod
    def opened(_event: TopologyOpenedEvent) -> None:
        return None

    def description_changed(self, event: TopologyDescriptionChangedEvent) -> None:
        new_primary = _writable_primary_address(event.new_description)
        with self._lock:
            if new_primary is None:
                if self._current_primary is not None:
                    self._primary_changed = True
                    self._current_primary = None
                return
            if (
                self._current_primary is not None
                and new_primary != self._current_primary
            ):
                self._primary_changed = True
            self._current_primary = new_primary

    @staticmethod
    def closed(_event: TopologyClosedEvent) -> None:
        return None


class PeriodicCalibrationSampler:
    __slots__ = (
        "_cadence_seconds",
        "_error",
        "_lock",
        "_points",
        "_rounds",
        "_send_hello",
        "_stop_event",
        "_thread",
    )

    def __init__(
        self,
        send_hello: Callable[[], Mapping[str, object]],
        *,
        cadence_seconds: float,
        rounds: int,
    ) -> None:
        if cadence_seconds <= 0:
            message = "cadence_seconds must be positive"
            raise BenchmarkConfigurationError(message)
        self._send_hello = send_hello
        self._cadence_seconds = cadence_seconds
        self._rounds = rounds
        self._points: list[CalibrationPoint] = []
        self._error: Exception | None = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            message = "PeriodicCalibrationSampler has already been started"
            raise BenchmarkConfigurationError(message)
        self.sample_now()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def sample_now(self) -> CalibrationPoint:
        point = sample_clock_offset(self._send_hello, rounds=self._rounds)
        with self._lock:
            self._points.append(point)
        return point

    def _run(self) -> None:
        while not self._stop_event.wait(self._cadence_seconds):
            try:
                self.sample_now()
            except Exception as error:  # noqa: BLE001
                with self._lock:
                    self._error = error
                return

    def stop(self) -> tuple[CalibrationPoint, ...]:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join()
        with self._lock:
            error = self._error
        if error is not None:
            message = f"periodic calibration sampling failed: {error}"
            raise BenchmarkSetupError(message) from error
        return self.points()

    def points(self) -> tuple[CalibrationPoint, ...]:
        with self._lock:
            return tuple(self._points)
