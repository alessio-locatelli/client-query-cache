from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pymongo.monitoring import TopologyListener

from benchmarks.stream_cost.errors import BenchmarkConfigurationError

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


def sample_clock_offset(
    send_hello: Callable[[], Mapping[str, object]], *, rounds: int
) -> ClockSample:
    if rounds <= 0:
        message = "rounds must be positive"
        raise BenchmarkConfigurationError(message)
    best: ClockSample | None = None
    for _ in range(rounds):
        wall_t0 = time.time()
        monotonic_t0 = time.monotonic()
        response = send_hello()
        wall_t1 = time.time()
        monotonic_t1 = time.monotonic()
        local_time = response["localTime"]
        assert isinstance(local_time, datetime)
        sample = ClockSample(
            wall_t0=wall_t0,
            wall_t1=wall_t1,
            monotonic_t0=monotonic_t0,
            monotonic_t1=monotonic_t1,
            server_time_seconds=_bson_datetime_to_epoch_seconds(local_time),
            election_id=response.get("electionId"),
        )
        if best is None or sample.round_trip_seconds < best.round_trip_seconds:
            best = sample
    assert best is not None
    return best


@dataclass(frozen=True, slots=True)
class CalibrationSeries:
    samples: tuple[ClockSample, ...]

    def __post_init__(self) -> None:
        if not self.samples:
            message = "at least one calibration sample is required"
            raise BenchmarkConfigurationError(message)

    @property
    def initial(self) -> ClockSample:
        return self.samples[0]

    def drift_seconds(self, sample: ClockSample) -> float:
        return abs(sample.offset_seconds - self.initial.offset_seconds)

    def combined_drift_uncertainty_seconds(self, sample: ClockSample) -> float:
        return self.initial.uncertainty_seconds + sample.uncertainty_seconds

    @property
    def total_uncertainty_seconds(self) -> float:
        candidates = [self.initial.uncertainty_seconds]
        candidates.extend(
            self.drift_seconds(sample) + self.combined_drift_uncertainty_seconds(sample)
            for sample in self.samples[1:]
        )
        return max(candidates)

    def exceeds_drift_tolerance(self, tolerance_seconds: float) -> bool:
        return any(
            self.drift_seconds(sample) > tolerance_seconds
            for sample in self.samples[1:]
        )

    @property
    def has_election_change(self) -> bool:
        election_ids = {
            sample.election_id
            for sample in self.samples
            if sample.election_id is not None
        }
        return len(election_ids) > 1

    def has_host_clock_step(self, *, tolerance_seconds: float) -> bool:
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
            for sample in self.samples[1:]
        )


def validate_cadence(
    cadence_seconds: float, threshold_seconds: float, *, max_fraction: float = 0.1
) -> None:
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
        self._primary_lost = False
        self._primary_changed = False

    @property
    def primary_changed(self) -> bool:
        with self._lock:
            return self._primary_changed

    @staticmethod
    def opened(_event: TopologyOpenedEvent) -> None:
        return None

    def description_changed(self, event: TopologyDescriptionChangedEvent) -> None:
        new_primary = _writable_primary_address(event.new_description)
        with self._lock:
            if new_primary is None:
                if self._current_primary is not None:
                    self._primary_lost = True
                return
            if self._current_primary is not None and (
                new_primary != self._current_primary or self._primary_lost
            ):
                self._primary_changed = True
            self._current_primary = new_primary
            self._primary_lost = False

    @staticmethod
    def closed(_event: TopologyClosedEvent) -> None:
        return None
