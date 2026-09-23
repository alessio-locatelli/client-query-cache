from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import pytest

from benchmarks.stream_cost import calibration as calibration_module
from benchmarks.stream_cost import pair_runner
from benchmarks.stream_cost.calibration import (
    CalibrationPoint,
    CalibrationSeries,
    ClockSample,
    TopologyChangeListener,
)
from benchmarks.stream_cost.consolidated_stream import (
    ConsolidatedStreamPairConfig,
    PairVariant,
    counterbalanced_pair_order,
)
from benchmarks.stream_cost.errors import (
    BenchmarkConfigurationError,
    BenchmarkSetupError,
)
from benchmarks.stream_cost.pair_runner import (
    PairResult,
    RunResult,
    run_consolidated_stream_pair,
    run_consolidated_stream_pairs,
)

if TYPE_CHECKING:
    from pymongo import MongoClient
    from pymongo.monitoring import TopologyDescriptionChangedEvent

pytestmark = pytest.mark.unit

_ORDER = (PairVariant.CONTROL, PairVariant.LOADED)


def _config(
    *, clock_drift_tolerance_seconds: float = 1.0
) -> ConsolidatedStreamPairConfig:
    return ConsolidatedStreamPairConfig(
        acceptable_lag_percentile=0.5,
        acceptable_lag_threshold_seconds=5.0,
        relevant_write_count=1,
        relevant_write_schedule_tolerance_seconds=1.0,
        relevant_write_count_tolerance=0,
        unrelated_write_minimum_count=1,
        unrelated_write_interval_seconds=0.5,
        clock_drift_tolerance_seconds=clock_drift_tolerance_seconds,
        calibration_cadence_seconds=0.5,
        pair_count=3,
        warmup_duration_seconds=0.01,
    )


def _clock_sample(
    *,
    wall_t0: float,
    offset: float,
    election_id: object = "election-1",
    monotonic_t0: float | None = None,
) -> ClockSample:
    resolved_monotonic_t0 = wall_t0 if monotonic_t0 is None else monotonic_t0
    wall_t1 = wall_t0 + 0.1
    monotonic_t1 = resolved_monotonic_t0 + 0.1
    mid = (wall_t0 + wall_t1) / 2
    return ClockSample(
        wall_t0=wall_t0,
        wall_t1=wall_t1,
        monotonic_t0=resolved_monotonic_t0,
        monotonic_t1=monotonic_t1,
        server_time_seconds=mid + offset,
        election_id=election_id,
    )


def _point(**kwargs: object) -> CalibrationPoint:
    sample = _clock_sample(**kwargs)  # type: ignore[arg-type]
    return CalibrationPoint(selected=sample, rounds=(sample,))


class _StubManager:
    __slots__ = ("closed",)

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _fake_run_result(variant: PairVariant) -> RunResult:
    return RunResult(
        variant=variant,
        relevant_write_count=1,
        unrelated_write_count_during_window=0,
        raw_lag_windows=(),
    )


def _patch_calibration(
    monkeypatch: pytest.MonkeyPatch, points: list[CalibrationPoint]
) -> None:
    iterator = iter(points)
    monkeypatch.setattr(
        calibration_module,
        "sample_clock_offset",
        lambda *_args, **_kwargs: next(iterator),
    )


def _patch_healthy_runs(monkeypatch: pytest.MonkeyPatch) -> _StubManager:
    manager = _StubManager()

    def fake_run_single(
        _client: object,
        _previous_manager: object,
        *,
        variant: PairVariant,
        **_kwargs: object,
    ) -> tuple[_StubManager, RunResult]:
        return manager, _fake_run_result(variant)

    monkeypatch.setattr(pair_runner, "_run_single", fake_run_single)
    return manager


def _dummy_client() -> MongoClient[dict[str, Any]]:
    return cast("MongoClient[dict[str, Any]]", None)


def test_rejects_too_few_relevant_collections() -> None:
    with pytest.raises(BenchmarkConfigurationError, match="at least"):
        run_consolidated_stream_pair(
            _dummy_client(),
            TopologyChangeListener(),
            database="db",
            relevant_collection_names=["only_one"],
            unrelated_collection_name="unrelated",
            config=_config(),
            schedule=(0.0,),
            order=_ORDER,
        )


def test_rejects_duplicate_relevant_collection_names() -> None:
    with pytest.raises(BenchmarkConfigurationError, match="duplicate"):
        run_consolidated_stream_pair(
            _dummy_client(),
            TopologyChangeListener(),
            database="db",
            relevant_collection_names=["a", "a"],
            unrelated_collection_name="unrelated",
            config=_config(),
            schedule=(0.0,),
            order=_ORDER,
        )


def test_rejects_an_unrelated_collection_that_is_also_relevant() -> None:
    with pytest.raises(BenchmarkConfigurationError, match="unrelated_collection_name"):
        run_consolidated_stream_pair(
            _dummy_client(),
            TopologyChangeListener(),
            database="db",
            relevant_collection_names=["a", "b"],
            unrelated_collection_name="a",
            config=_config(),
            schedule=(0.0,),
            order=_ORDER,
        )


def test_rejects_an_order_missing_a_variant() -> None:
    with pytest.raises(BenchmarkConfigurationError, match="order must contain"):
        run_consolidated_stream_pair(
            _dummy_client(),
            TopologyChangeListener(),
            database="db",
            relevant_collection_names=["a", "b"],
            unrelated_collection_name="unrelated",
            config=_config(),
            schedule=(0.0,),
            order=(PairVariant.CONTROL, PairVariant.CONTROL),
        )


def test_rejects_an_order_with_extra_duplicate_entries() -> None:
    with pytest.raises(BenchmarkConfigurationError, match="order must contain"):
        run_consolidated_stream_pair(
            _dummy_client(),
            TopologyChangeListener(),
            database="db",
            relevant_collection_names=["a", "b"],
            unrelated_collection_name="unrelated",
            config=_config(),
            schedule=(0.0,),
            order=cast(
                "tuple[PairVariant, PairVariant]",
                (PairVariant.CONTROL, PairVariant.LOADED, PairVariant.CONTROL),
            ),
        )


def test_propagates_a_failure_before_any_manager_is_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_calibration(monkeypatch, [_point(wall_t0=0.0, offset=10.0)])

    def failing_run_single(*_args: object, **_kwargs: object) -> None:
        message = "simulated setup failure"
        raise BenchmarkSetupError(message)

    monkeypatch.setattr(pair_runner, "_run_single", failing_run_single)

    with pytest.raises(BenchmarkSetupError, match="simulated setup failure"):
        run_consolidated_stream_pair(
            _dummy_client(),
            TopologyChangeListener(),
            database="db",
            relevant_collection_names=["a", "b"],
            unrelated_collection_name="unrelated",
            config=_config(),
            schedule=(0.0,),
            order=_ORDER,
        )


def _server_event(
    address: tuple[str, int],
) -> TopologyDescriptionChangedEvent:
    @dataclass(frozen=True, slots=True)
    class _FakeServerDescription:
        is_writable: bool

    @dataclass(frozen=True, slots=True)
    class _FakeTopologyDescription:
        servers: dict[tuple[str, int], _FakeServerDescription]

        def server_descriptions(self) -> dict[tuple[str, int], _FakeServerDescription]:
            return self.servers

    @dataclass(frozen=True, slots=True)
    class _FakeEvent:
        new_description: _FakeTopologyDescription

    return cast(
        "TopologyDescriptionChangedEvent",
        _FakeEvent(
            _FakeTopologyDescription(
                {address: _FakeServerDescription(is_writable=True)}
            )
        ),
    )


def test_fails_when_the_listener_observed_a_primary_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listener = TopologyChangeListener()
    manager = _StubManager()

    def fake_run_single(
        _client: object,
        _previous_manager: object,
        *,
        variant: PairVariant,
        **_kwargs: object,
    ) -> tuple[_StubManager, RunResult]:
        if variant is PairVariant.LOADED:
            listener.description_changed(_server_event(("host", 1)))
            listener.description_changed(_server_event(("host", 2)))
        return manager, _fake_run_result(variant)

    monkeypatch.setattr(pair_runner, "_run_single", fake_run_single)
    _patch_calibration(
        monkeypatch,
        [
            _point(wall_t0=0.0, offset=10.0),
            _point(wall_t0=1.0, offset=10.0),
            _point(wall_t0=2.0, offset=10.0),
        ],
    )

    with pytest.raises(BenchmarkSetupError, match="primary changed"):
        run_consolidated_stream_pair(
            _dummy_client(),
            listener,
            database="db",
            relevant_collection_names=["a", "b"],
            unrelated_collection_name="unrelated",
            config=_config(),
            schedule=(0.0,),
            order=_ORDER,
        )


def test_fails_when_calibration_samples_show_an_election_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_healthy_runs(monkeypatch)
    _patch_calibration(
        monkeypatch,
        [
            _point(wall_t0=0.0, offset=10.0, election_id="a"),
            _point(wall_t0=1.0, offset=10.0, election_id="b"),
            _point(wall_t0=2.0, offset=10.0, election_id="a"),
        ],
    )

    with pytest.raises(BenchmarkSetupError, match="primary changed"):
        run_consolidated_stream_pair(
            _dummy_client(),
            TopologyChangeListener(),
            database="db",
            relevant_collection_names=["a", "b"],
            unrelated_collection_name="unrelated",
            config=_config(),
            schedule=(0.0,),
            order=_ORDER,
        )


def test_fails_when_clock_drift_exceeds_the_pre_registered_tolerance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_healthy_runs(monkeypatch)
    _patch_calibration(
        monkeypatch,
        [
            _point(wall_t0=0.0, offset=10.0),
            _point(wall_t0=1.0, offset=10.5),
            _point(wall_t0=2.0, offset=10.0),
        ],
    )

    with pytest.raises(BenchmarkSetupError, match="clock drift"):
        run_consolidated_stream_pair(
            _dummy_client(),
            TopologyChangeListener(),
            database="db",
            relevant_collection_names=["a", "b"],
            unrelated_collection_name="unrelated",
            config=_config(clock_drift_tolerance_seconds=0.1),
            schedule=(0.0,),
            order=_ORDER,
        )


def test_fails_when_the_hosts_wall_clock_was_stepped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_healthy_runs(monkeypatch)
    _patch_calibration(
        monkeypatch,
        [
            _point(wall_t0=0.0, offset=10.0),
            _point(wall_t0=10.0, offset=10.0, monotonic_t0=1.0),
            _point(wall_t0=20.0, offset=10.0, monotonic_t0=11.0),
        ],
    )

    with pytest.raises(BenchmarkSetupError, match="wall clock was stepped"):
        run_consolidated_stream_pair(
            _dummy_client(),
            TopologyChangeListener(),
            database="db",
            relevant_collection_names=["a", "b"],
            unrelated_collection_name="unrelated",
            config=_config(clock_drift_tolerance_seconds=0.5),
            schedule=(0.0,),
            order=_ORDER,
        )


def test_returns_a_pair_result_when_everything_checks_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _patch_healthy_runs(monkeypatch)
    _patch_calibration(
        monkeypatch,
        [
            _point(wall_t0=0.0, offset=10.0),
            _point(wall_t0=1.0, offset=10.0),
            _point(wall_t0=2.0, offset=10.0),
        ],
    )

    pair_result = run_consolidated_stream_pair(
        _dummy_client(),
        TopologyChangeListener(),
        database="db",
        relevant_collection_names=["a", "b"],
        unrelated_collection_name="unrelated",
        config=_config(),
        schedule=(0.0,),
        order=_ORDER,
    )

    assert pair_result.control.variant is PairVariant.CONTROL
    assert pair_result.loaded.variant is PairVariant.LOADED
    assert pair_result.control.raw_lag_windows == ()
    assert pair_result.loaded.raw_lag_windows == ()
    assert manager.closed is True


def test_a_stale_primary_change_from_a_prior_pair_does_not_fail_this_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_healthy_runs(monkeypatch)
    _patch_calibration(
        monkeypatch,
        [
            _point(wall_t0=0.0, offset=10.0),
            _point(wall_t0=1.0, offset=10.0),
            _point(wall_t0=2.0, offset=10.0),
        ],
    )
    listener = TopologyChangeListener()
    listener.description_changed(_server_event(("host", 1)))
    listener.description_changed(_server_event(("host", 2)))
    assert listener.primary_changed is True

    pair_result = run_consolidated_stream_pair(
        _dummy_client(),
        listener,
        database="db",
        relevant_collection_names=["a", "b"],
        unrelated_collection_name="unrelated",
        config=_config(),
        schedule=(0.0,),
        order=_ORDER,
    )

    assert pair_result.control.variant is PairVariant.CONTROL


def test_fails_when_relevant_write_counts_do_not_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _StubManager()

    def fake_run_single(
        _client: object,
        _previous_manager: object,
        *,
        variant: PairVariant,
        **_kwargs: object,
    ) -> tuple[_StubManager, RunResult]:
        count = 1 if variant is PairVariant.CONTROL else 10
        return manager, RunResult(
            variant=variant,
            relevant_write_count=count,
            unrelated_write_count_during_window=0,
            raw_lag_windows=(),
        )

    monkeypatch.setattr(pair_runner, "_run_single", fake_run_single)
    _patch_calibration(
        monkeypatch,
        [
            _point(wall_t0=0.0, offset=10.0),
            _point(wall_t0=1.0, offset=10.0),
            _point(wall_t0=2.0, offset=10.0),
        ],
    )

    with pytest.raises(BenchmarkSetupError, match="relevant writes"):
        run_consolidated_stream_pair(
            _dummy_client(),
            TopologyChangeListener(),
            database="db",
            relevant_collection_names=["a", "b"],
            unrelated_collection_name="unrelated",
            config=_config(),
            schedule=(0.0,),
            order=_ORDER,
        )


def test_send_hello_uses_the_primary_read_preference() -> None:
    calls: list[dict[str, object]] = []

    class _StubAdmin:
        @staticmethod
        def command(name: str, **kwargs: object) -> dict[str, object]:
            calls.append({"name": name, **kwargs})
            return {"ok": 1.0}

    class _StubClient:
        admin = _StubAdmin()

    pair_runner._send_hello(cast("MongoClient[dict[str, Any]]", _StubClient()))

    assert calls[0]["name"] == "hello"


def test_await_condition_raises_on_timeout() -> None:
    with pytest.raises(BenchmarkSetupError, match="boom"):
        pair_runner._await_condition(
            lambda: False,
            timeout_seconds=0.01,
            poll_interval_seconds=0.001,
            timeout_message="boom",
        )


def test_await_condition_returns_once_the_predicate_is_true() -> None:
    calls: list[None] = []

    def predicate() -> bool:
        calls.append(None)
        return len(calls) >= 2

    pair_runner._await_condition(
        predicate,
        timeout_seconds=1.0,
        poll_interval_seconds=0.001,
        timeout_message="unreachable",
    )
    assert len(calls) == 2


def test_rejects_a_schedule_length_mismatching_the_configured_count() -> None:
    with pytest.raises(BenchmarkConfigurationError, match="relevant_write_count"):
        run_consolidated_stream_pair(
            _dummy_client(),
            TopologyChangeListener(),
            database="db",
            relevant_collection_names=["a", "b"],
            unrelated_collection_name="unrelated",
            config=_config(),
            schedule=(0.0, 0.1),
            order=_ORDER,
        )


def test_run_single_closes_the_manager_when_execute_run_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _StubManager()
    monkeypatch.setattr(pair_runner, "reset_run_state", lambda *_a, **_k: manager)

    def failing_execute_run(*_args: object, **_kwargs: object) -> None:
        message = "simulated execute failure"
        raise BenchmarkSetupError(message)

    monkeypatch.setattr(pair_runner, "_execute_run", failing_execute_run)

    with pytest.raises(BenchmarkSetupError, match="simulated execute failure"):
        pair_runner._run_single(
            _dummy_client(),
            None,
            database="db",
            relevant_collection_names=["a", "b"],
            unrelated_collection_name="unrelated",
            config=_config(),
            schedule=(0.0,),
            variant=PairVariant.CONTROL,
            cache_config=None,
        )

    assert manager.closed is True


def test_run_consolidated_stream_pairs_runs_the_configured_pair_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[PairVariant, PairVariant]] = []

    def fake_run_pair(
        *_args: object,
        order: tuple[PairVariant, PairVariant],
        **_kwargs: object,
    ) -> PairResult:
        calls.append(order)
        return PairResult(
            control=_fake_run_result(PairVariant.CONTROL),
            loaded=_fake_run_result(PairVariant.LOADED),
            calibration=CalibrationSeries(points=(_point(wall_t0=0.0, offset=10.0),)),
        )

    monkeypatch.setattr(pair_runner, "run_consolidated_stream_pair", fake_run_pair)

    pair_results = run_consolidated_stream_pairs(
        _dummy_client(),
        TopologyChangeListener(),
        database="db",
        relevant_collection_names=["a", "b"],
        unrelated_collection_name="unrelated",
        config=_config(),
        schedule=(0.0,),
    )

    assert len(pair_results) == 3
    assert calls == list(counterbalanced_pair_order(3))
