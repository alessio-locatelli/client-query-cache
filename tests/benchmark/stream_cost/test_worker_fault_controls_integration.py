from __future__ import annotations

import json
import multiprocessing
import time
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

import pytest
from pymongo import MongoClient

from benchmarks.stream_cost.shared_cache import fault_recovery, run
from benchmarks.stream_cost.shared_cache.dataset import seed_catalogue
from benchmarks.stream_cost.shared_cache.fault_timeline import merge_chunks
from benchmarks.stream_cost.shared_cache.protocol import (
    Registration,
    fault_recovery_cells,
    smoke_cells,
)
from benchmarks.stream_cost.shared_cache.window import (
    ProcessGroup,
    _spec,
    _verify_ready,
    _workload,
)
from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits
from client_query_cache._types import BsonDict, NonNegativeFloat, NonNegativeInt

if TYPE_CHECKING:
    from collections.abc import Callable
    from multiprocessing.connection import Connection

    from benchmarks.stream_cost.shared_cache.worker import Payload

pytestmark = pytest.mark.integration

_REGISTRATION = Path("reports/shared-worker-cache/v4/config.json")
_FAULT_REGISTRATION = Path("reports/worker-fault-recovery/v8/config.json")
_CONTAINER_LIMITS = ResourceLimits(cpus=1.0, memory="1g")
_WORKER_COUNT = 2
_WORKER_RATE = 10.0
_WINDOW_SECONDS = 5.0
_FAULT_WAIT_SECONDS = 20.0
_FAULT_POLL_SECONDS = 0.05


@pytest.mark.timeout(900)
def test_registered_fault_smoke_dispatches_every_case_path(
    tmp_path: Path,
) -> None:
    output = tmp_path / "fault-smoke.json"

    run.main(
        [
            "--smoke",
            "--phase",
            "fault",
            "--config",
            str(_FAULT_REGISTRATION),
            "--output",
            str(output),
        ]
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    cells = report["cells"]
    assert report["phase"] == "fault-smoke"
    assert report["smoke"] is True
    assert report["evidence"] is False
    assert len(cells) == 7
    assert {(cell["fault_case"], cell["path"]) for cell in cells} == {
        ("connection-loss", "direct"),
        ("connection-loss", "independent"),
        ("stepdown", "direct"),
        ("stepdown", "independent"),
        ("history-loss", "independent"),
        ("worker-restart", "direct"),
        ("worker-restart", "independent"),
    }
    for cell in cells:
        counts = cell["requests"]["counts"]
        assert cell["healthy"] is True
        assert cell["injection"]["injected"] is True
        assert sum(counts.values()) == cell["requests"]["offered"]
        assert cell["recovery"]["recovered"] is True
        assert cell["outcome"] == "recovered"
        assert cell["correctness"]["available"] is True
        assert cell["correctness"]["passed"] is True
        assert cell["correctness"]["probed"] > 0


@pytest.mark.timeout(120)
def test_unrecovered_fault_skips_post_recovery_correctness_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registration = Registration.load(_FAULT_REGISTRATION)
    cell = next(
        cell
        for cell in fault_recovery_cells(registration, smoke=True)
        if cell.fault_case == "connection-loss" and cell.path == "direct"
    )
    cell = replace(
        cell,
        workers=_WORKER_COUNT,
        rate=_WORKER_RATE,
        window_seconds=_WINDOW_SECONDS,
        warmup_seconds=0,
        injection_offset_seconds=2.0,
        recovery_deadline_seconds=1.0,
    )

    def never_recovered(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"recovered": False, "recovery_offset": None}

    monkeypatch.setattr(fault_recovery, "detect_recovery", never_recovered)

    with IsolatedReplicaSet(_CONTAINER_LIMITS) as topology:
        record = fault_recovery.run_recovery_fault_window(topology, registration, cell)

    assert record["outcome"] == "not-recovered"
    assert record["correctness"] == {
        "available": False,
        "passed": None,
        "probed": 0,
    }


@pytest.fixture(scope="module")
def registration() -> Registration:
    return Registration.load(_REGISTRATION)


@pytest.mark.timeout(180)
@pytest.mark.parametrize(
    ("fault_case", "path"),
    [
        pytest.param("connection-loss", "direct", id="sever-direct"),
        pytest.param("connection-loss", "independent", id="sever-independent"),
        pytest.param("history-loss", "independent", id="history-loss-independent"),
        pytest.param("worker-restart", "direct", id="restart-direct"),
        pytest.param("worker-restart", "independent", id="restart-independent"),
    ],
)
def test_worker_fault_controls_recover_and_serve_schedule_share(
    registration: Registration,
    fault_case: Literal["connection-loss", "history-loss", "worker-restart"],
    path: Literal["direct", "independent"],
) -> None:
    base_cell = next(
        cell
        for cell in smoke_cells(registration)
        if cell.path == path and cell.workload == "hot"
    )
    cell = replace(
        base_cell,
        phase="integration",
        model="async",
        workers=_WORKER_COUNT,
        path=path,
        rate=_WORKER_RATE,
        window_seconds=_WINDOW_SECONDS,
        warmup_seconds=0,
    )
    workload = _workload(registration, cell)
    with (
        IsolatedReplicaSet(_CONTAINER_LIMITS) as topology,
        MongoClient[BsonDict](topology.uri) as writer,
        ProcessGroup(
            multiprocessing.get_context("spawn"),
            registration.number("shutdown_seconds"),
        ) as group,
    ):
        seed_catalogue(
            writer,
            database=cast("str", registration.raw["database"]),
            collection=cast("str", registration.raw["collection"]),
            seed=cast("int", registration.raw["seed"]),
            profile=registration.profile(cell.profile),  # type: ignore[arg-type]
            categories=registration.categories,
        )
        startup_deadline = time.monotonic() + registration.number("startup_seconds")
        for index in range(_WORKER_COUNT):
            spec = _spec(
                registration,
                cell,
                workload,
                topology.uri,
                index=index,
                attachment=None,
                timeline_enabled=True,
            )
            group.start_worker(replace(spec, controls_enabled=True))
        ready = group.collect("ready", startup_deadline)
        _verify_ready(group, cell, workload, ready, startup_deadline)
        initial_openings = [cast("int", sample["streams"]) for sample in ready]
        expected_streams = int(path == "independent")
        assert initial_openings == [expected_streams] * _WORKER_COUNT
        stale_probe = group.control_worker(
            0,
            "probe",
            keys=[workload.keys[0]],
            revision=1,
        )
        assert stale_probe["probe_ok"] is False

        if fault_case == "worker-restart":
            group.kill_and_replace(0)
            replacement_ready = _receive_ready(
                group.connections[0],
                time.monotonic() + registration.number("startup_seconds"),
            )
            assert replacement_ready["streams"] == expected_streams
        elif fault_case == "connection-loss":
            fault_deadline = time.monotonic() + _FAULT_WAIT_SECONDS
            for index in range(_WORKER_COUNT):
                group.control_worker(index, "sever")
                if path == "independent":
                    prior = initial_openings[index]

                    def reopened(
                        sample: Payload, *, expected_openings: NonNegativeInt = prior
                    ) -> bool:
                        return (
                            sample["health"] == "healthy"
                            and _stream_openings(sample) > expected_openings
                        )

                    _await_worker_state(
                        group,
                        index,
                        reopened,
                        fault_deadline,
                    )
        else:
            fault_deadline = time.monotonic() + _FAULT_WAIT_SECONDS
            for index in range(_WORKER_COUNT):
                before = group.control_worker(index, "snapshot")
                entries = before["entries"]
                assert isinstance(entries, int)
                assert entries > 0
                group.control_worker(index, "lose-history")
                prior = _stream_openings(before)

                def history_reopened(
                    sample: Payload,
                    *,
                    expected_openings: NonNegativeInt = prior,
                ) -> bool:
                    entries_after = sample["entries"]
                    return (
                        sample["health"] == "healthy"
                        and _stream_openings(sample) > expected_openings
                        and entries_after == 0
                    )

                _await_worker_state(
                    group,
                    index,
                    history_reopened,
                    fault_deadline,
                )

        window_start = time.monotonic() + 0.25
        for connection in group.connections:
            connection.send(window_start)
        samples = group.collect(
            "sample",
            window_start
            + _WINDOW_SECONDS
            + registration.number("drain_seconds")
            + _FAULT_WAIT_SECONDS,
        )

        assert len(samples) == _WORKER_COUNT
        for index, sample in enumerate(samples):
            loop = cast("Payload", sample["loop"])
            offered = loop["offered"]
            completed = loop["completed"]
            assert isinstance(offered, int)
            assert isinstance(completed, int)
            assert offered > 0
            assert completed == offered
            assert loop["errors"] == 0
            openings = _stream_openings(sample)
            if path == "direct":
                assert openings == 0
            elif fault_case in {"connection-loss", "history-loss"}:
                assert openings > initial_openings[index]
            else:
                assert openings >= expected_streams
            events, snapshots = merge_chunks(group.received_timeline(index))
            terminal = [
                event for event in events if event["state"] in {"completed", "failed"}
            ]
            assert len(terminal) == completed
            assert snapshots
            assert all(
                "scheduled_offset" in event and "completed_offset" in event
                for event in terminal
            )


def _stream_openings(sample: Payload) -> NonNegativeInt:
    openings = sample["streams"]
    assert isinstance(openings, int)
    return openings


def _await_worker_state(
    group: ProcessGroup,
    index: NonNegativeInt,
    predicate: Callable[[Payload], bool],
    deadline: NonNegativeFloat,
) -> Payload:
    while time.monotonic() < deadline:
        sample = group.control_worker(index, "snapshot")
        if predicate(sample):
            return sample
        time.sleep(_FAULT_POLL_SECONDS)
    raise AssertionError("worker did not reach the expected post-fault state")


def _receive_ready(connection: Connection, deadline: NonNegativeFloat) -> Payload:
    remaining = deadline - time.monotonic()
    assert remaining > 0
    assert connection.poll(remaining)
    sample = cast("Payload", connection.recv())
    assert sample["kind"] == "ready"
    return sample
