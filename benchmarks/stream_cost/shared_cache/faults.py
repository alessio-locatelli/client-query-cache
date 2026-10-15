from __future__ import annotations

import multiprocessing
import os
import signal
import socket
import struct
import time
from contextlib import ExitStack
from dataclasses import asdict
from typing import TYPE_CHECKING, cast

from pymongo import MongoClient
from pymongo.errors import PyMongoError

from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.multiprocess_run import receive
from benchmarks.stream_cost.shared_cache.dataset import seed_catalogue
from benchmarks.stream_cost.shared_cache.protocol import FaultCell, fault_applicability
from benchmarks.stream_cost.shared_cache.safety import (
    closed_peer,
    local_key,
    raw_connection,
    verify_published_payloads,
)
from benchmarks.stream_cost.shared_cache.window import (
    ProcessGroup,
    _count,
    _spec,
    _workload,
)
from client_query_cache._shared.attachment import SyncEndpoint
from client_query_cache._shared.wire import (
    ProtocolError,
    encode_frame,
    encode_key,
)
from client_query_cache._types import BsonDict, NonNegativeFloat, NonNegativeInt

if TYPE_CHECKING:
    from collections.abc import Callable

    from benchmarks.stream_cost.shared_cache.protocol import Cell, Registration
    from benchmarks.stream_cost.topology import IsolatedReplicaSet
    from client_query_cache._shared.attachment import AttachmentConfig
    from client_query_cache._shared.coordinator import Message


def _require(condition: object, message: str) -> None:
    if not condition:
        raise LookupError(message)


def _mapping(record: Message, key: str) -> Message:
    value = record[key]
    assert isinstance(value, dict)
    return value


def _timestamp(record: Message) -> NonNegativeFloat:
    value = record["monotonic"]
    assert isinstance(value, float)
    return value


def _number(record: Message, key: str) -> NonNegativeFloat:
    value = record[key]
    assert isinstance(value, (int, float)), f"{key} is not a numeric observation"
    return value


class FaultTrial:
    __slots__ = (
        "attachment",
        "cell",
        "checks",
        "deadline",
        "events",
        "group",
        "probes",
        "ready_state",
        "registration",
        "revision",
        "stopped",
        "uri",
    )

    def __init__(
        self,
        group: ProcessGroup,
        registration: Registration,
        cell: FaultCell,
        uri: str,
        attachment: AttachmentConfig,
    ) -> None:
        self.group = group
        self.registration = registration
        self.cell = cell
        self.uri = uri
        self.attachment = attachment
        self.deadline = time.monotonic() + cell.window_seconds
        self.events: dict[str, NonNegativeFloat] = {}
        self.checks: list[str] = []
        self.probes: dict[str, list[Message]] = {}
        self.revision: NonNegativeInt = 0
        self.ready_state = False
        self.stopped = False

    def wait(self, predicate: Callable[[], bool]) -> None:
        while not predicate():
            if time.monotonic() >= self.deadline:
                message = (
                    "fault trial observation deadline expired in "
                    f"{predicate.__qualname__}"
                )
                raise BenchmarkSetupError(message)
            time.sleep(self.registration.number("phases", "fault", "poll_seconds"))

    def owner(self, operation: str = "sample", **fields: object) -> Message:
        return self.group.owner_request({"op": operation, **fields}, self.deadline)

    def observe(self) -> Message:
        return _mapping(self.owner(), "observation")

    def workers(self, operation: str = "probe", **fields: object) -> list[Message]:
        check_recovery = operation in {"probe", "prime"} and (
            "injection" not in self.events or "recovery" in self.events
        )
        before = self._owner_state() if check_recovery else None
        for connection in self.group.connections:
            connection.send({"op": operation, "revision": self.revision, **fields})
        observations = [
            receive(connection, self.deadline, "probe")
            for connection in self.group.connections
        ]
        self.probes[operation] = observations
        if before is not None:
            self.ready_state = self._record_readiness(
                before, observations, self._owner_state(), operation=operation
            )
        return observations

    def _owner_state(self) -> Message:
        observation = self.observe()
        return {
            **_mapping(
                _mapping(observation, "databases"),
                str(self.registration.raw["database"]),
            ),
            "incarnation": observation["incarnation"],
            "monotonic": observation["observed_monotonic"],
        }

    def ready(self) -> bool:
        self.workers()
        return self.ready_state

    def _record_readiness(
        self,
        before: Message,
        probes: list[Message],
        after: Message,
        *,
        operation: str = "probe",
    ) -> bool:
        self.probes[operation + "-owner"] = [before, after]
        hits = [probe for probe in probes if probe["hit"]]
        if hits:
            first = min(_number(probe, "hit_at") for probe in hits)
            if "first_hit" not in self.events:
                self.events["first_hit"] = first
            if "recovery" in self.events:
                _require(
                    after["available"]
                    and after["progress_fresh"]
                    and before["incarnation"] == after["incarnation"]
                    and all(
                        not probe["unsafe_hit"]
                        and probe["incarnation"] == after["incarnation"]
                        and _number(after, "available_since")
                        <= _number(probe, "hit_at")
                        and _number(after, "fresh_since") <= _number(probe, "hit_at")
                        and _timestamp(before)
                        <= _number(probe, "hit_at")
                        <= _number(probe, "last_hit_at")
                        <= _timestamp(after)
                        for probe in hits
                    ),
                    "cached hit lacks safe owner and worker observations "
                    "across the read",
                )
        if (
            after["available"]
            and after["progress_fresh"]
            and any(
                probe["eligible"] and probe["incarnation"] == after["incarnation"]
                for probe in probes
            )
        ):
            observed_at = time.monotonic()
            if "readiness" not in self.events:
                self.events["readiness"] = observed_at
            return True
        return False

    def rewarmed(self) -> bool:
        probes = self.workers("prime")
        observation = self.observe()
        keys = self.registration.number("hot_keys")
        complete = _count(observation, "cache", "entry_count") >= keys
        if self.cell.path == "shared-index":
            complete = (
                complete
                and _count(observation, "shared_index", "published") >= keys
                and all(probe["resident_keys"] == keys for probe in probes)
            )
        else:
            complete = complete and all(probe["all_hits"] for probe in probes)
        if complete:
            self.events["rewarming"] = time.monotonic()
        return complete

    def capture(self, index: NonNegativeInt = 0) -> Message:
        connection = self.group.connections[index]
        connection.send({"op": "capture"})
        _require(
            connection.poll(max(0.0, self.deadline - time.monotonic())),
            "capture timed out",
        )
        capture = connection.recv()
        _require(
            capture is not None and capture["r"] == "miss",
            "scenario did not obtain its capture",
        )
        assert isinstance(capture, dict)
        return capture

    def stale_admission(self, capture: Message) -> None:
        before = _count(self.observe(), "counters", "rejected_admissions")
        connection = self.group.connections[0]
        connection.send({"op": "admit", "handle": capture["handle"]})
        receive(connection, self.deadline, "sent")
        self.wait(
            lambda: _count(self.observe(), "counters", "rejected_admissions") > before
        )
        self.checks.append("obsolete capture rejected")

    def detect(self) -> None:
        def fenced() -> bool:
            probes = self.workers("detect")
            safe = all(
                not probe["hit"]
                and (
                    probe["resident_keys"] == 0
                    if self.cell.path == "shared-index"
                    else probe["bypass"]
                )
                for probe in probes
            )
            if safe:
                self.events["detection"] = max(_timestamp(probe) for probe in probes)
            return safe

        self.wait(fenced)
        self.checks.append("all workers fenced faulted state")

    def _start_local_traffic(self) -> None:
        probes = self.workers("traffic-start")
        _require(
            all(
                probe["hits"] == self.registration.number("hot_keys")
                for probe in probes
            ),
            "continuous local traffic did not start with the complete hot set",
        )

    def _stop_local_traffic(self) -> None:
        probes = self.workers("traffic-stop")
        initial = self.probes["traffic-start"]
        _require(
            all(
                _number(probe, "sweeps") > _number(before, "sweeps")
                and _number(probe, "misses") > 0
                and _number(probe, "last_hit") <= self.events["detection"]
                for before, probe in zip(initial, probes, strict=True)
            ),
            "continuous local traffic did not fence across the fault transition",
        )
        self.checks.append(
            "continuous local reads crossed injection and remained fenced"
        )

    def _reattach_to_warm_owner(self, incarnation: object) -> None:
        connection = self.group.connections[0]
        keys = self.registration.number("hot_keys")

        def warm_first() -> bool:
            before = self._owner_state()
            operation = (
                "prime" if before["available"] and before["progress_fresh"] else "probe"
            )
            connection.send({"op": operation, "revision": self.revision})
            first = receive(connection, self.deadline, "probe")
            if self._record_readiness(
                before, [first], self._owner_state(), operation="warm-first"
            ):
                _require(
                    first["incarnation"] != incarnation,
                    "first worker failed to reattach",
                )
                return operation == "prime" and first["resident_keys"] == keys
            return False

        self.wait(warm_first)
        probes = self.workers("local-only")
        _require(
            probes[0]["resident_keys"] == self.registration.number("hot_keys")
            and all(
                probe["incarnation"] == incarnation and probe["resident_keys"] == 0
                for probe in probes[1:]
            ),
            "old mappings selected entries from the warm replacement owner",
        )
        self.checks.append(
            "old mappings stayed fenced while replacement publication was warm"
        )

    def restart(self) -> None:
        owner = self.group.owner
        control = self.group.owner_control
        assert owner is not None
        assert control is not None
        owner.join(max(0.0, self.deadline - time.monotonic()))
        _require(not owner.is_alive(), "old owner failed to exit")
        control.close()
        self.events["recovery"] = time.monotonic()
        self.attachment = self.group.start_owner(
            self.registration, self.uri, self.deadline, self.cell.path
        )

    def replace_worker(self, index: NonNegativeInt) -> None:
        process = self.group.processes[index]
        process.kill()
        process.join(max(0.0, self.deadline - time.monotonic()))
        _require(not process.is_alive(), "killed worker failed to exit")
        self.group.connections[index].close()
        self.group.processes.pop(index)
        self.group.connections.pop(index)
        self.events["recovery"] = time.monotonic()
        self.group.start_worker(
            _spec(
                self.registration,
                self.cell,
                _workload(self.registration, self.cell),
                self.uri,
                index=index,
                attachment=self.attachment,
            )
        )
        receive(self.group.connections[-1], self.deadline, "attached")

    def inject(self) -> None:
        case = self.cell.fault_case
        if case == "torn-read-stress":
            self.stress()
            return
        if case == "malformed-frames":
            self.malformed()
            return
        if case == "slow-reader":
            self.slow_reader()
            return
        if case == "cancellation-during-publication":
            self.cancel()
            return
        if case in {"worker-killed-with-capture", "worker-replacement"}:
            if case == "worker-killed-with-capture":
                self.capture(1)
                self.wait(lambda: self.observe()["captures"] == 1)
            self.events["injection"] = time.monotonic()
            self.replace_worker(1)
            self.wait(lambda: self.observe()["captures"] == 0)
            self.checks.append(
                "killed worker captures released and replacement attached"
            )
            return
        if case == "shutdown-during-startup":
            self.owner("pause-watch")
            _require(
                not any(probe["hit"] for probe in self.workers()),
                "startup unexpectedly served a cached hit",
            )
            _require(
                self.owner()["activation_pending"],
                "shutdown did not overlap stream activation",
            )
            assert self.group.owner_control is not None
            self.events["injection"] = time.monotonic()
            self.group.owner_control.send("close")
            self.detect()
            assert self.group.owner is not None
            self.group.owner.join(max(0.0, self.deadline - time.monotonic()))
            _require(self.group.owner.exitcode == 0, "owner did not shut down cleanly")
            self.events["recovery"] = time.monotonic()
            self.restart()
            self.checks.append("shutdown during activation left reads native")
            return
        capture = (
            None
            if case in {"coordinator-pause", "owner-pause-during-local-hits"}
            else self.capture()
        )
        incarnation = self.observe()["incarnation"]
        local_traffic = case in {
            "owner-kill-during-local-hits",
            "owner-pause-during-local-hits",
        }
        if local_traffic:
            self._start_local_traffic()
        self.events["injection"] = time.monotonic()
        if case in {
            "coordinator-restart",
            "owner-kill-during-local-hits",
            "reattachment-after-restart",
        }:
            owner = self.group.owner
            assert owner is not None
            if case == "coordinator-restart":
                assert self.group.owner_control is not None
                self.group.owner_control.send("close")
            else:
                owner.kill()
            self.detect()
            if local_traffic:
                self._stop_local_traffic()
            if case == "coordinator-restart":
                owner.join(max(0.0, self.deadline - time.monotonic()))
                _require(owner.exitcode == 0, "coordinator restart was not graceful")
                self.checks.append("coordinator shut down gracefully before restart")
            self.restart()
            if case == "reattachment-after-restart":
                self._reattach_to_warm_owner(incarnation)
            self.wait(self.ready)
            assert capture is not None
            self.stale_admission(capture)
            probes = self.workers()
            _require(
                all(probe["incarnation"] != incarnation for probe in probes),
                "worker retained previous owner incarnation",
            )
            self.checks.append("all workers attached to replacement incarnation")
        elif case in {
            "coordinator-pause",
            "owner-pause-during-local-hits",
            "watch-pause",
        }:
            if case == "watch-pause":
                self.owner("pause-watch")
            else:
                assert self.group.owner_pid is not None
                os.kill(self.group.owner_pid, signal.SIGSTOP)
                self.stopped = True
            self.detect()
            if local_traffic:
                self._stop_local_traffic()
            if case == "watch-pause":
                assert capture is not None
                self.stale_admission(capture)
            self.events["recovery"] = time.monotonic()
            if case == "watch-pause":
                self.owner("resume-watch")
            else:
                assert self.group.owner_pid is not None
                os.kill(self.group.owner_pid, signal.SIGCONT)
                self.stopped = False
        else:
            assert capture is not None
            openings = _count(self.owner(), "commands", "stream:opened")
            if case == "stream-interruption":
                self.owner("pause-watch")
                self.owner("sever")
            else:
                self.owner("hold-history")
                self.wait(lambda: _count(self.observe(), "cache", "entry_count") == 0)
                self.stale_admission(capture)
            self.events["recovery"] = time.monotonic()
            self.owner(
                "resume-watch" if case == "stream-interruption" else "resume-history"
            )
            self.wait(
                lambda: _count(self.owner(), "commands", "stream:opened") > openings
            )
            if case == "history-loss":
                _require(
                    _count(self.observe(), "cache", "entry_count") == 0,
                    "history loss retained old cache entries",
                )
                self.checks.append("history loss cleared entries before recovery")
            else:
                before = _count(self.observe(), "counters", "admitted")
                connection = self.group.connections[0]
                connection.send({"op": "admit", "handle": capture["handle"]})
                receive(connection, self.deadline, "sent")
                self.wait(
                    lambda: _count(self.observe(), "counters", "admitted") > before
                )
                self.checks.append("resumed stream preserved a valid capture")

    def malformed(self) -> None:
        self.events["injection"] = time.monotonic()
        frames = (
            struct.pack("<I", 5) + b"\x05\x00\x00\x00\xff",
            struct.pack("<I", 10**8),
            encode_frame({"v": 2, "id": 1, "op": "hello"}),
        )
        before = _count(self.observe(), "counters", "protocol_errors")
        for frame in frames:
            with raw_connection(self.attachment, authenticate=False) as peer:
                peer.sendall(frame)
                _require(closed_peer(peer), "malformed peer remained attached")
        self.wait(
            lambda: (
                _count(self.observe(), "counters", "protocol_errors")
                == before + len(frames)
            )
        )
        _require(
            any(probe["hit"] for probe in self.workers()),
            "malformed peers disrupted healthy workers",
        )
        self.checks.append("malformed peers rejected while healthy workers hit")

    def slow_reader(self) -> None:
        before = _count(self.observe(), "counters", "detached")
        with raw_connection(self.attachment, authenticate=True) as peer:
            peer.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
            self.events["injection"] = time.monotonic()
            peer.sendall(encode_frame({"v": 1, "id": 1, "op": "observe"}) * 64)
            self.wait(lambda: _count(self.observe(), "counters", "detached") > before)
            _require(
                any(probe["hit"] for probe in self.workers()),
                "slow peer blocked healthy workers",
            )
            self.events["recovery"] = time.monotonic()
        self.checks.append("slow peer detached without blocking workers")

    def cancel(self) -> None:
        self.events["injection"] = time.monotonic()
        paused = self.owner(
            "pause-server",
            seconds=self.registration.number("phases", "fault", "pause_seconds"),
        )
        resumes_at = paused["resumes_at"]
        assert isinstance(resumes_at, float)
        self.events["recovery"] = resumes_at
        connection = self.group.connections[2]
        connection.send({"op": "cancel"})
        _require(
            connection.poll(max(0.0, self.deadline - time.monotonic())),
            "cancelled selection did not finish",
        )
        cancelled = connection.recv()
        _require(cancelled["cancelled"], "selection was not cancelled")
        self.wait(lambda: time.monotonic() >= resumes_at)
        self.wait(self.ready)
        self.wait(
            lambda: any(
                probe["late_replies"] > cancelled["late_replies_before"]
                for probe in self.workers()
                if probe["index"] == 2
            )
        )
        self.wait(lambda: self.observe()["captures"] == 0)
        self.checks.append("cancelled selection released its capture")

    def execute(self, writer: MongoClient[BsonDict]) -> None:
        if self.cell.fault_case != "shutdown-during-startup":
            self.wait(self.ready)
            self.wait(self.rewarmed)
            self.wait(lambda: all(probe["hit"] for probe in self.workers()))
        self.events.clear()
        self.probes.clear()
        self.deadline = time.monotonic() + self.cell.window_seconds
        self.inject()
        if self.cell.fault_case not in {"malformed-frames", "torn-read-stress"}:
            self.wait(self.ready)
            self.wait(
                lambda: (
                    "first_hit" in self.events
                    or (self.ready() and "first_hit" in self.events)
                )
            )
            self.wait(self.rewarmed)
            before = _count(self.owner(), "invalidations")
            writer[cast("str", self.registration.raw["database"])][
                cast("str", self.registration.raw["collection"])
            ].update_one({"_id": 0}, {"$set": {"revision": 1}})
            self.wait(lambda: _count(self.owner(), "invalidations") > before)
            self.revision = 1
            self.workers(key=0)
            self.checks.append(
                "post-recovery invalidation returned current revision on every worker"
            )

    def stress(self) -> None:
        _require(
            self.cell.path == "shared-index", "torn-read-stress requires shared-index"
        )
        endpoint = SyncEndpoint(self.attachment)
        try:
            namespace = [
                self.registration.raw["database"],
                self.registration.raw["collection"],
            ]
            metadata = endpoint.request({"op": "metadata", "ns": namespace})
            assert metadata is not None
            assert metadata["r"] == "ok"
            keys = tuple(
                range(cast("NonNegativeInt", self.registration.raw["hot_keys"]))
            )
            encoded = tuple((key, local_key(key)) for key in keys)
            shape = encode_key("fault-stress")
            published: dict[NonNegativeInt, set[bytes]] = {key: set() for key in keys}
            for connection in self.group.connections:
                connection.send({"op": "stress"})
            self.group.collect("reading", self.deadline)
            self.events["injection"] = time.monotonic()
            for churn in range(
                cast(
                    "NonNegativeInt",
                    self.registration.number("phases", "fault", "stress_rounds"),
                )
            ):
                for key, identity in encoded:
                    self.owner("invalidate", collection=namespace[1], key=key)
                    capture = endpoint.request(
                        {
                            "op": "select-identity",
                            "ns": namespace,
                            "epoch": metadata["epoch"],
                            "identity": identity,
                            "shape": shape,
                        }
                    )
                    _require(
                        capture is not None and capture["r"] == "miss",
                        "stress admission did not obtain a capture",
                    )
                    assert capture is not None
                    value = f"{key}:{churn}:".encode() * (300 + churn % 7 * 11)
                    published[key].add(value)
                    endpoint.send(
                        {"op": "admit", "handle": capture["handle"], "value": value}
                    )
            for connection in self.group.connections:
                connection.send("stop")
            observed_reads = 0
            for connection in self.group.connections:
                _require(
                    connection.poll(max(0.0, self.deadline - time.monotonic())),
                    "stress reader did not return",
                )
                observation = connection.recv()
                verify_published_payloads(observation["observed"], published)
                _require(
                    observation["reads"] > 0,
                    "stress worker observed no published payloads",
                )
                observed_reads += observation["reads"]
            self.checks.append(
                f"{observed_reads} concurrent reads contained only published payloads"
            )
        finally:
            endpoint.close()


def _close_fault_workers(group: ProcessGroup) -> None:
    for connection in group.connections:
        try:
            connection.send("close")
        except BrokenPipeError:
            pass


def run_fault_window(
    replica: IsolatedReplicaSet,
    registration: Registration,
    cell: Cell,
) -> Message:
    assert isinstance(cell, FaultCell)
    applicability = fault_applicability(registration)[cell.fault_case]
    record: Message = {
        **asdict(cell),
        "healthy": False,
        "events": {},
        "durations": {},
        "checks": [],
    }
    try:
        _execute_fault_window(replica, registration, cell, record, applicability)
    except (
        BenchmarkSetupError,
        LookupError,
        AssertionError,
        EOFError,
        OSError,
        PyMongoError,
        ProtocolError,
    ) as error:
        record["healthy"] = False
        record["failure"] = f"{type(error).__name__}: {error}"
    return record


def _execute_fault_window(
    replica: IsolatedReplicaSet,
    registration: Registration,
    cell: FaultCell,
    record: Message,
    applicability: dict[str, bool],
) -> None:
    with ExitStack() as resources:
        writer = resources.enter_context(
            MongoClient[BsonDict](replica.uri, **registration.section("client_options"))  # type: ignore[arg-type]
        )
        database = cast("str", registration.raw["database"])
        collection = cast("str", registration.raw["collection"])
        seed_catalogue(
            writer,
            database=database,
            collection=collection,
            seed=cast("int", registration.raw["seed"]),
            profile=registration.profile(cell.profile),  # type: ignore[arg-type]
            categories=registration.categories,
        )
        group = resources.enter_context(
            ProcessGroup(
                multiprocessing.get_context("spawn"),
                registration.number("shutdown_seconds"),
            )
        )
        deadline = time.monotonic() + registration.number("startup_seconds")
        attachment = group.start_owner(registration, replica.uri, deadline, cell.path)
        for index in range(cell.workers):
            group.start_worker(
                _spec(
                    registration,
                    cell,
                    _workload(registration, cell),
                    replica.uri,
                    index=index,
                    attachment=attachment,
                )
            )
        resources.callback(_close_fault_workers, group)
        group.collect("attached", deadline)
        trial = FaultTrial(group, registration, cell, replica.uri, attachment)
        try:
            trial.execute(writer)
            record["healthy"] = True
        finally:
            if trial.stopped:
                assert group.owner_pid is not None
                os.kill(group.owner_pid, signal.SIGCONT)
            record["events"] = trial.events
            record["checks"] = trial.checks
            record["probes"] = trial.probes
            record["durations"] = {
                name: None
                if not applies
                or name not in trial.events
                or ("injection" if name == "detection" else "recovery")
                not in trial.events
                else trial.events[name]
                - trial.events["injection" if name == "detection" else "recovery"]
                for name, applies in applicability.items()
            }
