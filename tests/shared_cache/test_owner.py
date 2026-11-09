from __future__ import annotations

import asyncio
import datetime as dt
import multiprocessing
import os
import secrets
import select
import selectors
import socket
import stat
import struct
import threading
import time
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypedDict
from unittest.mock import Mock

import pytest

from benchmarks.stream_cost.shared_cache.owner import PausableOwner, pause_owner
from benchmarks.stream_cost.shared_cache.window import attachment_for
from client_query_cache._core.canonical import canonicalize
from client_query_cache._core.codec import encode_value
from client_query_cache._core.collection_metadata import CollectionProbeResult
from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.order_sensitive_keys import order_sensitive_key
from client_query_cache._core.snapshots import BypassReason
from client_query_cache._core.stream_events import route_change_event
from client_query_cache._shared import adapters, attachment, coordinator
from client_query_cache._shared.attachment import (
    AsyncEndpoint,
    AsyncLocalIndex,
    AttachmentConfigurationError,
    ControlAttachment,
    EndpointCounters,
    LocalIndex,
    SyncEndpoint,
    control_handshake,
)
from client_query_cache._shared.coordinator import (
    OwnerConfig,
    SharedCacheOwner,
)
from client_query_cache._shared.diagnostics import (
    SharedBypassReason,
    SharedStreamStatus,
)
from client_query_cache._shared.shared_index import SharedIndexLimits
from client_query_cache._shared.wire import (
    PROTOCOL_VERSION,
    KeyCache,
    ProtocolError,
    decode_frame,
    encode_frame,
    encode_key,
)
from client_query_cache._shared_index import ReaderIndex
from client_query_cache._types import NonNegativeFloat, NonNegativeInt, PositiveFloat
from tests.descriptors import file_identity, references
from tests.shared_cache.conftest import LIMITS, Racing, refresh_metadata, wait_for

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator
    from multiprocessing.connection import Connection

    from faker import Faker

    from client_query_cache._shared.attachment import Message
    from client_query_cache._shared.coordinator import ActivationState
    from client_query_cache._shared_index import SessionRing

pytestmark = pytest.mark.unit

_DATABASE = "unreachable"
# Linux raises any smaller SO_SNDBUF request to its minimum send buffer.
_SMALLEST_SEND_BUFFER = 1
_HIT_BYTES = 48 * 1024
_RPC_DEADLINE_SECONDS = 0.05
_COLLECTION = "catalogue"
_NAMESPACE = NamespaceId(_DATABASE, _COLLECTION)
_SHAPE = "full"
_SHARED_BUDGET = 64 * 1024
_SHARED_MAX_ENTRY = 16 * 1024
_FILLER_BYTES = 15 * 1024
_FILLERS = 5
_REUSE_KEY = 99
_ENTRY_BYTES = 14 * 1024
_FILLERS_BEFORE_EVICTION = 3
_SHARED_INDEX = SharedIndexLimits(
    slots=64, arena_bytes=1024 * 1024, namespaces=4, ring_tokens=64
)
_HOUR_NS = 3_600 * 10**9
_PARTIAL_SEND_BYTES = 5
_SMALL_RING = 4
_OVERFLOWING_HITS = 32
_PAUSE_SECONDS = 1.0
_SWEEP_GAP_SECONDS = 0.2
_POLL_QUIET_MS = 50
_POLL_STOP_MS = 120


def _config(socket_directory: Path, **changes: object) -> OwnerConfig:
    config = OwnerConfig(
        socket_path=str(socket_directory / "owner.sock"),
        capability=secrets.token_bytes(32),
        mongodb_uri="mongodb://127.0.0.1:9/?directConnection=true",
        client_options={"serverSelectionTimeoutMS": 100},
        databases=(_DATABASE,),
        budget_bytes=1024 * 1024,
        max_entry_bytes=64 * 1024,
        max_await_time_ms=100,
        limits=LIMITS,
        lag_capture=(1, 1, 0),
        enable_telemetry=True,
    )
    return replace(config, **changes)  # type: ignore[arg-type]


def _serving(config: OwnerConfig) -> Iterator[SharedCacheOwner]:
    instance = PausableOwner(config)
    instance.bind()
    parent, child = multiprocessing.Pipe()
    serving = threading.Thread(target=instance.serve, args=(child,))
    serving.start()
    yield instance
    parent.send("close")
    serving.join(10)
    instance.close()


@pytest.fixture(params=[True], ids=["enabled"])
def owner_telemetry(request: pytest.FixtureRequest) -> bool:
    assert isinstance(request.param, bool)
    return request.param


@pytest.fixture
def owner(
    socket_directory: Path, request: pytest.FixtureRequest, owner_telemetry: bool
) -> Iterator[SharedCacheOwner]:
    limits = getattr(request, "param", {})
    yield from _serving(
        _config(
            socket_directory,
            limits=replace(LIMITS, **limits),
            enable_telemetry=owner_telemetry,
        )
    )


@pytest.fixture
def shared_owner(
    socket_directory: Path, request: pytest.FixtureRequest, owner_telemetry: bool
) -> Iterator[SharedCacheOwner]:
    changes = getattr(request, "param", {})
    yield from _serving(
        _config(
            socket_directory,
            budget_bytes=_SHARED_BUDGET,
            max_entry_bytes=_SHARED_MAX_ENTRY,
            shared_index=replace(_SHARED_INDEX, **changes),
            enable_telemetry=owner_telemetry,
        )
    )


@dataclass(slots=True)
class _PollingLoop:
    owner: SharedCacheOwner
    control: Connection
    milliseconds: NonNegativeInt = 0
    timeouts: list[PositiveFloat] = field(default_factory=list)
    sweeps: list[NonNegativeFloat] = field(default_factory=list)
    drains: list[NonNegativeFloat] = field(default_factory=list)

    def monotonic(self) -> NonNegativeFloat:
        return self.milliseconds / 1000

    def select(
        self, timeout: PositiveFloat
    ) -> list[tuple[selectors.SelectorKey, NonNegativeInt]]:
        self.timeouts.append(timeout)
        self.milliseconds += round(timeout * 1000)
        if self.milliseconds >= _POLL_STOP_MS:
            return [
                (
                    self.owner._selector.get_key(self.control.fileno()),
                    selectors.EVENT_READ,
                )
            ]
        return []


@pytest.fixture
def polling_loop(
    socket_directory: Path, monkeypatch: pytest.MonkeyPatch, owner_telemetry: bool
) -> Iterator[_PollingLoop]:
    instance = SharedCacheOwner(
        _config(
            socket_directory,
            enable_telemetry=owner_telemetry,
            shared_index=replace(
                _SHARED_INDEX, local_miss_admission=True, native_admission_queue=True
            ),
        )
    )
    parent, child = multiprocessing.Pipe()
    parent.send("close")
    loop = _PollingLoop(instance, child)
    sweep = SharedCacheOwner._sweep
    drain = SharedCacheOwner._drain_admissions

    def record_sweep(owner: SharedCacheOwner, now: NonNegativeFloat) -> None:
        loop.sweeps.append(now)
        sweep(owner, now)

    def record_drain(owner: SharedCacheOwner, *, all_pending: bool = False) -> None:
        loop.drains.append(loop.monotonic())
        drain(owner, all_pending=all_pending)

    instance._admission_poll_until = _POLL_QUIET_MS / 1000
    monkeypatch.setattr(coordinator, "time", loop)
    monkeypatch.setattr(instance._selector, "select", loop.select)
    monkeypatch.setattr(SharedCacheOwner, "_sweep", record_sweep)
    monkeypatch.setattr(SharedCacheOwner, "_drain_admissions", record_drain)
    yield loop
    child.close()
    parent.close()
    instance.close()


@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
def test_recent_admissions_poll_without_accelerating_maintenance(
    polling_loop: _PollingLoop,
) -> None:
    polling_loop.owner.serve(polling_loop.control)

    assert polling_loop.timeouts == pytest.approx([0.001] * 50 + [0.05] * 2)
    assert polling_loop.sweeps == pytest.approx([0.001, 0.1])
    assert polling_loop.drains == pytest.approx(
        [milliseconds / 1000 for milliseconds in range(1, 51)] + [0.1]
    )


@pytest.fixture
def endpoints() -> Iterator[Callable[[SharedCacheOwner], SyncEndpoint]]:
    opened: list[SyncEndpoint] = []

    def open_endpoint(owner: SharedCacheOwner) -> SyncEndpoint:
        endpoint = SyncEndpoint(attachment_for(owner.config))
        opened.append(endpoint)
        return endpoint

    yield open_endpoint
    for endpoint in opened:
        endpoint.close()


@pytest.fixture
def peers() -> Iterator[Callable[[SharedCacheOwner], socket.socket]]:
    opened: list[socket.socket] = []

    def authenticated(owner: SharedCacheOwner) -> socket.socket:
        peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        opened.append(peer)
        peer.settimeout(5)
        peer.connect(owner.config.socket_path)
        peer.sendall(encode_frame(attachment_for(owner.config).hello()))
        _read_reply(peer)
        return peer

    yield authenticated
    for peer in opened:
        peer.close()


@pytest.fixture
def raw_peer() -> Iterator[socket.socket]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as peer:
        peer.settimeout(5)
        yield peer


@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
def test_peer_uid_rejection_preserves_same_user_attachment(
    owner: SharedCacheOwner,
    raw_peer: socket.socket,
    monkeypatch: pytest.MonkeyPatch,
    endpoints: Callable[[SharedCacheOwner], SyncEndpoint],
) -> None:
    original_uid = os.geteuid
    monkeypatch.setattr(os, "geteuid", lambda: original_uid() + 1)
    raw_peer.connect(owner.config.socket_path)
    assert raw_peer.recv(1) == b""
    if owner.config.enable_telemetry:
        assert owner.counters.unauthorized == 1
    monkeypatch.setattr(os, "geteuid", original_uid)
    _activate(owner)
    assert _metadata(endpoints(owner)) is not None


@pytest.fixture
def controls() -> Iterator[Callable[[SharedCacheOwner], ControlAttachment]]:
    opened: list[ControlAttachment] = []

    def attach(owner: SharedCacheOwner) -> ControlAttachment:
        control = control_handshake(attachment_for(owner.config))
        opened.append(control)
        return control

    yield attach
    for control in opened:
        control.sock.close()


@pytest.fixture
def writable_control(
    shared_owner: SharedCacheOwner,
) -> Iterator[tuple[ControlAttachment, NonNegativeInt]]:
    peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    peer.settimeout(5)
    peer.connect(shared_owner.config.socket_path)
    peer.sendall(
        encode_frame(attachment_for(shared_owner.config).hello(role="control"))
    )
    _reply, descriptors, _flags, _address = socket.recv_fds(peer, 262_144, 2)
    assert len(descriptors) == 2
    try:
        reader = ReaderIndex(
            descriptors[0],
            descriptors[1],
            enable_telemetry=shared_owner.config.enable_telemetry,
        )
        yield ControlAttachment(peer, reader), descriptors[1]
    finally:
        peer.close()
        for descriptor in descriptors:
            os.close(descriptor)


@pytest.fixture
def contender(owner: SharedCacheOwner) -> Iterator[SharedCacheOwner]:
    instance = SharedCacheOwner(owner.config)
    yield instance
    instance.close()


@pytest.fixture
def local_index(shared_owner: SharedCacheOwner) -> Iterator[LocalIndex]:
    local = LocalIndex.attach(attachment_for(shared_owner.config))
    yield local
    local.close()


@pytest.fixture
def handshake_listener(socket_directory: Path) -> Iterator[socket.socket]:
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(socket_directory / "handshake.sock"))
    listener.listen()
    yield listener
    listener.close()


def _metadata(endpoint: SyncEndpoint) -> Message | None:
    return refresh_metadata(endpoint.request, NamespaceId(_DATABASE, "catalogue"))


@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
def test_failed_stream_activation_bypasses_and_retries(
    owner: SharedCacheOwner, endpoints: Callable[[SharedCacheOwner], SyncEndpoint]
) -> None:
    endpoint = endpoints(owner)

    first = _metadata(endpoint)
    wait_for(lambda: owner._activation[_DATABASE][0] == "failed")
    held = _metadata(endpoint)
    wait_for(
        lambda: (
            _metadata(endpoint) is not None
            and owner._activation[_DATABASE][0] == "pending"
        )
    )

    assert first is not None
    assert held is not None
    assert first["reason"] == held["reason"] == SharedBypassReason.STREAM_STARTING


@pytest.mark.parametrize(
    ("activation", "available", "progress", "expected"),
    [
        pytest.param(
            None,
            False,
            False,
            (SharedStreamStatus.NOT_STARTED, SharedBypassReason.STREAM_STARTING),
            id="untouched",
        ),
        pytest.param(
            "pending",
            False,
            False,
            (SharedStreamStatus.STARTING, SharedBypassReason.STREAM_STARTING),
            id="starting",
        ),
        pytest.param(
            "failed",
            False,
            False,
            (SharedStreamStatus.STARTUP_FAILED, SharedBypassReason.STREAM_STARTING),
            id="startup-failed",
        ),
        pytest.param(
            "active",
            False,
            True,
            (SharedStreamStatus.UNAVAILABLE, SharedBypassReason.STREAM_UNAVAILABLE),
            id="unavailable",
        ),
        pytest.param(
            "active",
            True,
            False,
            (SharedStreamStatus.PROGRESS_EXPIRED, SharedBypassReason.PROGRESS_EXPIRED),
            id="progress-expired",
        ),
        pytest.param(
            "active", True, True, (SharedStreamStatus.HEALTHY, None), id="healthy"
        ),
    ],
)
def test_stream_status_matches_the_reason_reads_bypass(
    owner: SharedCacheOwner,
    activation: ActivationState | None,
    available: bool,
    progress: bool,
    expected: tuple[SharedStreamStatus, SharedBypassReason | None],
) -> None:
    status, gate_reason = expected
    now = time.monotonic()
    if activation is not None:
        owner._activation[_DATABASE] = (activation, now)
    owner.core.set_database_available(_DATABASE, available=available)
    if progress:
        owner.progress.observed[_DATABASE] = now

    databases = owner.observation(now)["databases"]

    assert isinstance(databases, dict)
    assert owner._stream_status(_DATABASE, now) is status
    assert databases[_DATABASE]["status"] == status.value
    assert owner._gate(_DATABASE, now) == gate_reason


def test_observation_reports_uptime_limits_and_tracked_namespaces(
    shared_owner: SharedCacheOwner,
) -> None:
    before = shared_owner.observation(shared_owner._started)
    shared_owner.core.create_namespace(_NAMESPACE)
    after = shared_owner.observation(shared_owner._started + 1.5)

    assert before["uptime_seconds"] == 0
    assert after["uptime_seconds"] == pytest.approx(1.5)
    assert before["namespaces"] == 0
    assert after["namespaces"] == 1
    assert after["limits"] == {
        "index_entries": _SHARED_INDEX.slots,
        "namespaces": _SHARED_INDEX.namespaces,
        "connections": LIMITS.connections,
    }


@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
def test_a_second_owner_cannot_bind_a_held_endpoint(
    contender: SharedCacheOwner,
) -> None:
    with pytest.raises(RuntimeError, match="already holds this endpoint"):
        contender.bind()


@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
def test_a_peer_that_disappears_before_its_reply_is_detached(
    owner: SharedCacheOwner,
) -> None:
    peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    peer.connect(owner.config.socket_path)
    peer.sendall(encode_frame(attachment_for(owner.config).hello()))
    peer.close()

    wait_for(lambda: not owner._connections)


def _activate(owner: SharedCacheOwner) -> None:
    owner._activation[_DATABASE] = ("active", time.monotonic())
    owner.progress.observed[_DATABASE] = time.monotonic() + 3600


@pytest.fixture(params=[False, True], ids=["disabled", "enabled"])
def policy_owner(
    socket_directory: Path,
    request: pytest.FixtureRequest,
) -> Iterator[SharedCacheOwner]:
    yield from _serving(
        _config(
            socket_directory,
            enable_telemetry=request.param,
            shared_index=_SHARED_INDEX,
        )
    )


def test_owner_keeps_progress_fencing_and_authorization_in_both_modes(
    policy_owner: SharedCacheOwner,
    endpoints: Callable[[SharedCacheOwner], SyncEndpoint],
) -> None:
    owner = policy_owner
    _activate(owner)
    endpoint = endpoints(owner)
    assert endpoint.config.enable_telemetry is owner.core.enable_telemetry
    metadata = _metadata(endpoint)
    assert metadata is not None
    assert metadata["r"] == "ok"
    now = time.monotonic()
    assert owner.lease_fresh(_DATABASE, now)
    pending = endpoint.request(_select_find())
    assert pending is not None
    assert pending["r"] == "miss"
    previous_lease = owner._lease(_DATABASE)
    owner.progress.observed[_DATABASE] = (
        now - owner.config.limits.progress_expiry_seconds * 2
    )
    assert not owner.lease_fresh(_DATABASE, now)
    assert owner._lease(_DATABASE) == previous_lease + 1
    bypass = _metadata(endpoint)
    assert bypass is not None
    assert bypass["reason"] == SharedBypassReason.PROGRESS_EXPIRED
    endpoint.send(
        {
            "op": "admit",
            "handle": pending["handle"],
            "value": encode_value({"stale": True}),
        }
    )
    assert _metadata(endpoint) is not None
    assert not owner._handles
    endpoint.send(
        {
            "op": "admit",
            "handle": pending["handle"],
            "value": encode_value({"stale": True}),
        }
    )
    assert _metadata(endpoint) is not None
    _activate(owner)
    recovered = _metadata(endpoint)
    assert recovered is not None
    assert recovered["r"] == "ok"
    unauthorized = replace(attachment_for(owner.config), capability=b"wrong-capability")
    with pytest.raises(AttachmentConfigurationError, match="unauthorized"):
        SyncEndpoint(unauthorized)
    if not owner.config.enable_telemetry:
        assert owner._counters is None
        assert owner.progress.counts is None
        assert owner.progress._fresh_since is None


@pytest.mark.parametrize("policy_owner", [False], indirect=True, ids=["disabled"])
def test_disabled_owner_diagnostic_request_does_not_stop_serving(
    policy_owner: SharedCacheOwner,
    endpoints: Callable[[SharedCacheOwner], SyncEndpoint],
) -> None:
    reply = endpoints(policy_owner).request({"op": "observe"})
    assert reply is not None
    assert reply["r"] == "error"
    reason = reply["reason"]
    assert isinstance(reason, str)
    assert "enable_telemetry=True" in reason
    _activate(policy_owner)
    metadata = _metadata(endpoints(policy_owner))
    assert metadata is not None
    assert metadata["r"] == "ok"


def test_disabled_command_listener_publishes_progress_with_one_clock_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published = Mock()
    progress = coordinator.UpstreamProgress(published, expiry_seconds=1.0)
    forbidden = Mock(side_effect=AssertionError("disabled command accounting ran"))
    monkeypatch.setattr(progress, "_count", forbidden)
    clock = Mock(return_value=1_500_000_000)
    monkeypatch.setattr(coordinator, "time", Mock(monotonic_ns=clock))
    event = Mock(command_name="getMore", database_name=_DATABASE)
    progress.started(event)
    progress.failed(event)
    progress.succeeded(event)
    assert progress.observed == {_DATABASE: 1.5}
    assert progress.counts is None
    assert progress._fresh_since is None
    published.assert_called_once_with(_DATABASE, 1_500_000_000)
    clock.assert_called_once_with()
    forbidden.assert_not_called()


@pytest.fixture(params=[False, True], ids=["disabled", "enabled"])
def activation_owner(
    socket_directory: Path,
    request: pytest.FixtureRequest,
) -> Iterator[SharedCacheOwner]:
    instance = SharedCacheOwner(
        _config(socket_directory, enable_telemetry=request.param)
    )
    yield instance
    instance.close()


@pytest.mark.parametrize("succeeds", [False, True], ids=["failed", "active"])
def test_activation_reads_a_new_clock_only_for_retry_expiry(
    activation_owner: SharedCacheOwner,
    monkeypatch: pytest.MonkeyPatch,
    *,
    succeeds: bool,
) -> None:
    activate = Mock(return_value=Mock() if succeeds else None)
    monkeypatch.setattr(type(activation_owner.streams), "activate_database", activate)
    retry_clock = Mock(return_value=3.0)
    monkeypatch.setattr(coordinator, "time", Mock(monotonic=retry_clock))
    activation_owner._run_activation(_DATABASE, 1.5)
    assert activation_owner._activation[_DATABASE] == (
        ("active", 1.5) if succeeds else ("failed", 3.0)
    )
    assert retry_clock.call_count == (0 if succeeds else 1)


def _select_find(**changes: object) -> Message:
    return {
        "op": "select-find",
        "ns": [_DATABASE, "catalogue"],
        "epoch": 0,
        "family": encode_key("family"),
        "limit": 4,
        **changes,
    }


def _read_reply(peer: socket.socket) -> bytes:
    (length,) = struct.unpack("<I", _read_exactly(peer, 4))
    return _read_exactly(peer, length)


def _read_exactly(peer: socket.socket, size: int) -> bytes:
    received = b""
    while len(received) < size:
        chunk = peer.recv(size - len(received))
        assert chunk
        received += chunk
    return received


@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
@pytest.mark.parametrize("operation", ["select-find", "select-namespace"])
def test_selection_reports_unavailable_streams_and_stale_epochs(
    owner: SharedCacheOwner,
    endpoints: Callable[[SharedCacheOwner], SyncEndpoint],
    operation: str,
) -> None:
    _activate(owner)
    assert owner.core.try_current_epoch(NamespaceId(_DATABASE, "catalogue")) is not None
    endpoint = endpoints(owner)

    stale = endpoint.request(
        _select_find(op=operation, shape=encode_key("shape"), epoch=7)
    )
    owner.core.set_database_available(_DATABASE, available=False)
    unavailable = endpoint.request(
        _select_find(op=operation, shape=encode_key("shape"))
    )

    assert stale is not None
    assert stale["r"] == "refresh"
    assert unavailable is not None
    assert unavailable["reason"] == SharedBypassReason.STREAM_UNAVAILABLE


@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
def test_stale_request_does_not_recreate_a_dropped_namespace(session: _Session) -> None:
    _activate(session.owner)
    namespace = NamespaceId(_DATABASE, "dropped")
    old_epoch = session.owner.core.try_current_epoch(namespace)
    assert old_epoch is not None

    session.owner.core.drop_namespace(namespace)
    reply = session.endpoint.request(_select_find(ns=list(namespace), epoch=old_epoch))

    assert reply is not None
    assert reply["r"] == "refresh"
    assert reply["epoch"] == 0
    assert reply["index_generation"] == 0
    assert not session.owner.core.has_namespace(namespace)


@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
@pytest.mark.parametrize(
    "message",
    [
        pytest.param(_select_find(limit="four"), id="find-limit"),
        pytest.param({"op": "rename", "ns": [_DATABASE, "catalogue"]}, id="operation"),
    ],
)
@pytest.mark.parametrize(
    "authenticated", [False, True], ids=["unauthenticated", "authenticated"]
)
def test_invalid_requests_after_the_gate_detach_the_peer(
    owner: SharedCacheOwner,
    peers: Callable[[SharedCacheOwner], socket.socket],
    raw_peer: socket.socket,
    message: Message,
    *,
    authenticated: bool,
) -> None:
    _activate(owner)
    assert owner.core.try_current_epoch(NamespaceId(_DATABASE, "catalogue")) is not None
    peer = peers(owner) if authenticated else raw_peer
    if not authenticated:
        peer.connect(owner.config.socket_path)

    peer.sendall(encode_frame({"v": 1, "id": 2, **message}))

    assert peer.recv(1) == b""
    if owner.config.enable_telemetry:
        assert owner.counters.protocol_errors == 1


def test_split_frames_are_reassembled(
    owner: SharedCacheOwner, peers: Callable[[SharedCacheOwner], socket.socket]
) -> None:
    peer = peers(owner)
    frame = encode_frame({"v": 1, "id": 2, "op": "observe"})

    peer.sendall(frame[:3])
    time.sleep(0.1)
    peer.sendall(frame[3:10])
    time.sleep(0.1)
    peer.sendall(frame[10:])

    assert b"group" in _read_reply(peer)


def test_a_reader_that_falls_behind_receives_every_queued_reply(
    owner: SharedCacheOwner, peers: Callable[[SharedCacheOwner], socket.socket]
) -> None:
    peer = peers(owner)
    peer.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4_096)
    replies = 200

    for request_id in range(replies):
        peer.sendall(encode_frame({"v": 1, "id": request_id, "op": "observe"}))
    time.sleep(0.3)
    received = [_read_reply(peer) for _ in range(replies)]

    assert len(received) == replies
    assert owner.counters.detached == 0


@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
@pytest.mark.parametrize("owner", [{"capture_seconds": 0.2}], indirect=True)
def test_capture_expiry_releases_handles_of_each_session(
    owner: SharedCacheOwner, endpoints: Callable[[SharedCacheOwner], SyncEndpoint]
) -> None:
    _activate(owner)
    assert owner.core.try_current_epoch(NamespaceId(_DATABASE, "catalogue")) is not None
    sessions = [endpoints(owner) for _ in range(2)]

    replies = [endpoint.request(_select_find()) for endpoint in sessions]
    wait_for(lambda: not owner._handles)

    assert all(reply is not None and reply["r"] == "miss" for reply in replies)
    assert not owner._handles


@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
@pytest.mark.parametrize(
    "owner",
    [{}, {"queued_bytes_per_connection": _HIT_BYTES // 2}],
    indirect=True,
    ids=["fits", "queue-full"],
)
def test_large_replies_obey_queue_bounds_and_flush_in_parts(
    owner: SharedCacheOwner,
    peers: Callable[[SharedCacheOwner], socket.socket],
    faker: Faker,
) -> None:
    _activate(owner)
    assert owner.core.try_current_epoch(NamespaceId(_DATABASE, "catalogue")) is not None
    peer = peers(owner)
    (connection,) = owner._connections.values()
    connection.sock.setsockopt(
        socket.SOL_SOCKET, socket.SO_SNDBUF, _SMALLEST_SEND_BUFFER
    )
    value = faker.binary(length=_HIT_BYTES)
    peer.sendall(encode_frame({"v": 1, "id": 1, **_select_find()}))
    handle = decode_frame(_read_reply(peer))["handle"]
    peer.sendall(
        encode_frame({"v": 1, "id": 0, "op": "admit", "handle": handle, "value": value})
    )

    peer.sendall(encode_frame({"v": 1, "id": 2, **_select_find()}))
    if owner.config.limits.queued_bytes_per_connection < len(value):
        assert peer.recv(1) == b""
        return
    wait_for(lambda: connection.writable)
    reply = decode_frame(_read_reply(peer))

    assert reply["r"] == "hit"
    assert reply["value"] == value


def _close_after_hello(listener: socket.socket, *, consume: bool) -> None:
    peer, _address = listener.accept()
    if consume:
        _read_reply(peer)
    else:
        select.select([peer], [], [], 5)
    peer.close()


@pytest.mark.parametrize(
    "consume",
    [pytest.param(True, id="eof"), pytest.param(False, id="reset")],
)
def test_an_owner_lost_during_the_handshake_leaves_requests_native(
    owner: SharedCacheOwner, handshake_listener: socket.socket, consume: bool
) -> None:
    config = replace(
        attachment_for(owner.config),
        socket_path=handshake_listener.getsockname(),
    )
    server = threading.Thread(
        target=_close_after_hello,
        args=(handshake_listener,),
        kwargs={"consume": consume},
    )
    server.start()
    endpoint = AsyncEndpoint(config)

    reply = asyncio.run(endpoint.request({"op": "observe"}))
    server.join(5)

    assert reply is None
    assert endpoint.counters.failures == 1
    assert endpoint.counters.connects == 0


@pytest.fixture
def owner_reply_sent(
    owner: SharedCacheOwner, monkeypatch: pytest.MonkeyPatch
) -> threading.Event:
    sent = threading.Event()
    flush = SharedCacheOwner._flush

    def notify(instance: SharedCacheOwner, connection: coordinator._Connection) -> None:
        flush(instance, connection)
        sent.set()

    monkeypatch.setattr(type(owner), "_flush", notify)
    return sent


@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
def test_a_reply_delivered_after_its_deadline_is_counted_as_late(
    owner: SharedCacheOwner, owner_reply_sent: threading.Event
) -> None:
    config = replace(
        attachment_for(owner.config), rpc_deadline_seconds=_RPC_DEADLINE_SECONDS
    )

    async def scenario() -> tuple[Message | None, EndpointCounters | None]:
        endpoint = await AsyncEndpoint.attach(config)
        owner_reply_sent.clear()
        expiry = time.monotonic() + _RPC_DEADLINE_SECONDS
        request = asyncio.create_task(
            endpoint.request({"op": "metadata-probe", "ns": [_DATABASE, _COLLECTION]})
        )
        await asyncio.sleep(0)
        wait_for(lambda: owner_reply_sent.is_set() and time.monotonic() > expiry)
        reply = await request
        await endpoint.close()
        return reply, endpoint._counters

    reply, counters = asyncio.run(scenario())

    assert reply is None
    if counters is not None:
        assert counters.timeouts == 1
        assert counters.late_replies == 1


@pytest.fixture(params=[False, True], ids=["timeout", "disconnected"])
def disconnected_transport(request: pytest.FixtureRequest) -> bool:
    assert isinstance(request.param, bool)
    return request.param


@pytest.fixture
def faulted_endpoint(
    owner: SharedCacheOwner,
    disconnected_transport: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[SyncEndpoint]:
    endpoint = SyncEndpoint(
        replace(
            attachment_for(owner.config), rpc_deadline_seconds=_RPC_DEADLINE_SECONDS
        )
    )
    if disconnected_transport:
        (connection,) = owner._connections.values()
        owner.detach(connection)
    else:
        handle = SharedCacheOwner._handle_request

        def delayed(
            instance: SharedCacheOwner,
            connection: coordinator._Connection,
            message: Message,
            now: NonNegativeFloat,
            *,
            queued: bool = False,
        ) -> Message | None:
            time.sleep(_RPC_DEADLINE_SECONDS * 2)
            return handle(instance, connection, message, now, queued=queued)

        monkeypatch.setattr(type(owner), "_handle_request", delayed)
    yield endpoint
    endpoint.close()


@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
def test_transport_failure_bypasses_in_both_modes(
    faulted_endpoint: SyncEndpoint, disconnected_transport: bool
) -> None:
    assert (
        faulted_endpoint.request(
            {"op": "metadata-cancel", "ns": [_DATABASE, _COLLECTION], "probe_token": 0}
        )
        is None
    )
    if faulted_endpoint.config.enable_telemetry:
        assert faulted_endpoint.counters.failures == int(disconnected_transport)
        assert faulted_endpoint.counters.timeouts == int(not disconnected_transport)


@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
@pytest.mark.parametrize("owner", [{"connections": 1}], indirect=True)
def test_connection_capacity_keeps_the_attached_peer_usable(
    owner: SharedCacheOwner,
    endpoints: Callable[[SharedCacheOwner], SyncEndpoint],
) -> None:
    endpoint = endpoints(owner)  # pytriage: TR5 - Attach before testing capacity.
    with pytest.raises(AttachmentConfigurationError, match="not reachable"):
        SyncEndpoint(attachment_for(owner.config))
    assert len(owner._connections) == 1
    assert _metadata(endpoint) is not None


def _index_stats(owner: SharedCacheOwner) -> Message:
    stats = owner.observation(time.monotonic())["shared_index"]
    assert isinstance(stats, dict)
    return stats


def _identity(key: int) -> bytes:
    return encode_key(canonicalize(order_sensitive_key(key)))


@dataclass(slots=True)
class _Session:
    owner: SharedCacheOwner
    endpoint: SyncEndpoint
    control: ControlAttachment
    slot: list[int]
    epoch: int

    def select(self, key: int) -> Message:
        reply = self.endpoint.request(
            {
                "op": "select-identity",
                "ns": [_DATABASE, _COLLECTION],
                "epoch": self.epoch,
                "identity": _identity(key),
                "shape": encode_key(_SHAPE),
            }
        )
        assert reply is not None
        return reply

    def admit(self, key: int, value: bytes) -> None:
        reply = self.select(key)
        assert reply["r"] == "miss"
        self.endpoint.send({"op": "admit", "handle": reply["handle"], "value": value})
        assert _metadata(self.endpoint) is not None

    def local(self, key: int) -> bytes | None:
        database, namespace = self.slot
        return self.control.reader.lookup(
            database, namespace, self.epoch, _identity(key), encode_key(_SHAPE)
        )


@pytest.fixture
def session(
    shared_owner: SharedCacheOwner,
    endpoints: Callable[[SharedCacheOwner], SyncEndpoint],
    controls: Callable[[SharedCacheOwner], ControlAttachment],
) -> _Session:
    _activate(shared_owner)
    assert shared_owner._index is not None
    shared_owner._index.set_progress(0, time.monotonic_ns() + _HOUR_NS)
    endpoint = endpoints(shared_owner)
    metadata = _metadata(endpoint)
    assert metadata is not None
    slot = metadata["slot"]
    epoch = metadata["epoch"]
    assert isinstance(slot, list)
    assert isinstance(epoch, int)
    return _Session(shared_owner, endpoint, controls(shared_owner), slot, epoch)


def _committed(session: _Session, value: bytes, _patch: pytest.MonkeyPatch) -> bytes:
    session.admit(1, value)
    return value


def _racing_decode(
    monkeypatch: pytest.MonkeyPatch, shape: object, racing: Racing
) -> None:
    decode = KeyCache.decode
    encoded = encode_key(shape)

    def decode_racing(cache: KeyCache, value: object) -> object:
        return racing if value == encoded else decode(cache, value)

    monkeypatch.setattr(KeyCache, "decode", decode_racing)


def _rolled_back(session: _Session, value: bytes, _patch: pytest.MonkeyPatch) -> None:
    core = session.owner.core
    racing = Racing(_SHAPE, lambda: core.record_write(_NAMESPACE, 1))
    assert (
        core.admit_identity_published(
            core.begin_identity_admission(_NAMESPACE, 1),
            racing,
            value,
            _identity(1),
            encode_key(_SHAPE),
        )
        is AdmissionOutcome.DECLINED_STALE
    )


def _written(session: _Session, value: bytes, _patch: pytest.MonkeyPatch) -> None:
    session.admit(1, value)
    session.owner.core.record_write(_NAMESPACE, 1)


def _reset(session: _Session, value: bytes, _patch: pytest.MonkeyPatch) -> None:
    session.admit(1, value)
    session.owner.core.clear_namespace(_NAMESPACE)


def _evicted(session: _Session, value: bytes, _patch: pytest.MonkeyPatch) -> None:
    session.admit(1, value)
    for key in range(2, 2 + _FILLERS):
        session.admit(key, encode_frame({"v": b"x" * _FILLER_BYTES}))


def _unavailable(session: _Session, value: bytes, _patch: pytest.MonkeyPatch) -> None:
    session.admit(1, value)
    session.owner.core.set_database_available(_DATABASE, available=False)


def _recovered(session: _Session, value: bytes, _patch: pytest.MonkeyPatch) -> bytes:
    session.admit(1, value)
    session.owner.core.set_database_available(_DATABASE, available=False)
    session.owner.core.set_database_available(_DATABASE, available=True)
    return value


@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
@pytest.mark.parametrize(
    "scenario",
    [
        pytest.param(_committed, id="committed-admission"),
        pytest.param(_rolled_back, id="rolled-back-admission"),
        pytest.param(_written, id="write"),
        pytest.param(_reset, id="namespace-reset"),
        pytest.param(_evicted, id="eviction"),
        pytest.param(_unavailable, id="unavailable"),
        pytest.param(_recovered, id="availability-restored"),
    ],
)
def test_published_entries_follow_the_owner_core(
    session: _Session,
    faker: Faker,
    monkeypatch: pytest.MonkeyPatch,
    scenario: Callable[[_Session, bytes, pytest.MonkeyPatch], bytes | None],
) -> None:
    value = encode_frame({"name": faker.name()})

    expected = scenario(session, value, monkeypatch)

    assert session.local(1) == expected


def test_descriptors_survive_a_partial_handshake_send(
    shared_owner: SharedCacheOwner,
    controls: Callable[[SharedCacheOwner], ControlAttachment],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    send_fds = socket.send_fds

    def partial(
        sock: socket.socket, buffers: list[memoryview], descriptors: list[int]
    ) -> int:
        return send_fds(sock, [buffers[0][:_PARTIAL_SEND_BYTES]], descriptors)

    monkeypatch.setattr(socket, "send_fds", partial)

    attached = controls(shared_owner).reader.incarnation

    assert attached == shared_owner.incarnation
    assert _index_stats(shared_owner)["sessions"] == 1


@pytest.mark.parametrize("shared_owner", [{"ring_tokens": _SMALL_RING}], indirect=True)
def test_a_full_hit_ring_drops_touches_without_failing_hits(
    session: _Session, faker: Faker
) -> None:
    value = encode_frame({"name": faker.name()})
    session.admit(1, value)

    hits = [session.local(1) for _ in range(_OVERFLOWING_HITS)]

    assert hits == [value] * _OVERFLOWING_HITS
    assert session.control.reader.dropped() > 0
    assert _index_stats(session.owner)["dropped_touches"] == (
        session.control.reader.dropped()
    )


@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
def test_an_rpc_hit_never_returns_a_reused_block(
    session: _Session, faker: Faker, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = encode_frame({"name": faker.name()})
    session.admit(1, value)
    core = session.owner.core
    reused: list[AdmissionOutcome] = []

    def evict_and_reuse() -> None:
        for filler in range(2, 2 + _FILLERS):
            capture = core.begin_identity_admission(_NAMESPACE, filler)
            core.admit_identity(capture, _SHAPE, "x" * _FILLER_BYTES)
        reused.append(
            core.admit_identity_published(
                core.begin_identity_admission(_NAMESPACE, _REUSE_KEY),
                _SHAPE,
                faker.binary(length=len(value)),
                _identity(_REUSE_KEY),
                encode_key(_SHAPE),
            )
        )

    _racing_decode(monkeypatch, _SHAPE, Racing(_SHAPE, evict_and_reuse, on_hash=False))

    reply = session.select(1)

    assert reused == [AdmissionOutcome.ADMITTED]
    assert core.lookup_identity_encoded(_NAMESPACE, 1, _SHAPE) is None
    assert reply["r"] == "miss" or reply["value"] == value


@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
def test_control_attachments_need_a_shared_index(owner: SharedCacheOwner) -> None:
    with pytest.raises(AttachmentConfigurationError, match="shared-index-disabled"):
        control_handshake(attachment_for(owner.config))


def test_control_connections_carry_no_requests(session: _Session) -> None:
    session.control.sock.sendall(encode_frame({"v": 1, "id": 1, "op": "observe"}))

    assert session.control.sock.recv(1) == b""
    assert session.owner.counters.protocol_errors == 1


def test_a_peer_lost_before_its_descriptors_are_sent_closes_them(
    shared_owner: SharedCacheOwner, monkeypatch: pytest.MonkeyPatch
) -> None:
    def blocked(*_arguments: object) -> int:
        raise BlockingIOError

    monkeypatch.setattr(socket, "send_fds", blocked)
    peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    peer.connect(shared_owner.config.socket_path)
    peer.sendall(encode_frame(attachment_for(shared_owner.config).hello("control")))
    wait_for(lambda: len(_pending_handovers(shared_owner)) == 1)
    [handover] = _pending_handovers(shared_owner)
    files = {
        file_identity(handover.index_descriptor),
        file_identity(handover.ring.descriptor()),
    }
    held = references(files)  # pytriage: TR5 (before the peer is lost)
    peer.close()

    wait_for(lambda: not shared_owner._connections)
    assert held - references(files) == Counter(files)
    assert _index_stats(shared_owner)["sessions"] == 0


def _pending_handovers(owner: SharedCacheOwner) -> list[coordinator._Handover]:
    return [
        connection.handover
        for connection in owner._connections.values()
        if connection.handover is not None
    ]


@pytest.mark.parametrize("shared_owner", [{"namespaces": 1}], indirect=True)
@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
def test_namespaces_beyond_the_slot_capacity_bypass_without_retention(
    session: _Session,
) -> None:
    other = NamespaceId(_DATABASE, "other")
    metadata = refresh_metadata(session.endpoint.request, other)
    assert metadata is not None
    assert metadata["r"] == "bypass"
    assert metadata["reason"] == "namespace_capacity"
    selection = session.endpoint.request(_select_find(ns=list(other)))
    assert selection is not None
    assert selection["r"] == "bypass"
    assert selection["reason"] == "namespace_capacity"
    assert not session.owner.core.has_namespace(other)
    assert session.owner.core.namespaces_for_database(_DATABASE) == [_NAMESPACE]
    assert session.owner.core.assigned_slot(other) is None
    if session.owner.config.enable_telemetry:
        assert _index_stats(session.owner)["published"] == 0


def _metadata_reply(
    owner: SharedCacheOwner,
    connection: coordinator._Connection,
    namespace: NamespaceId,
    token: object,
) -> Message | None:
    return owner._handle_request(
        connection,
        {"op": "metadata", "ns": list(namespace), "probe_token": token},
        time.monotonic(),
    )


def _probe_token(
    owner: SharedCacheOwner, connection: coordinator._Connection, namespace: NamespaceId
) -> object:
    probe = owner._handle_request(
        connection, {"op": "metadata-probe", "ns": list(namespace)}, time.monotonic()
    )
    assert probe is not None
    assert probe["r"] == "probe"
    return probe["probe_token"]


@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
@pytest.mark.parametrize("shared_owner", [{"namespaces": 1}], indirect=True)
def test_metadata_slot_assignment_is_serialized_with_namespace_drop(
    shared_owner: SharedCacheOwner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def allow_database(
        _owner: SharedCacheOwner, _database: str, _now: NonNegativeFloat
    ) -> None:
        return None

    monkeypatch.setattr(SharedCacheOwner, "_gate", allow_database)
    namespace = NamespaceId(_DATABASE, "first")
    replacement = NamespaceId(_DATABASE, "replacement")
    with socket.socket() as sock:
        connection = coordinator._Connection(sock)
        connection.session = 1
        first = _metadata_reply(
            shared_owner,
            connection,
            namespace,
            _probe_token(shared_owner, connection, namespace),
        )
        assert first is not None
        assert first["r"] == "ok"
        repeated_token = _probe_token(shared_owner, connection, namespace)

        shared_owner.core.drop_namespace(namespace)
        stale = _metadata_reply(shared_owner, connection, namespace, repeated_token)
        replacement_reply = _metadata_reply(
            shared_owner,
            connection,
            replacement,
            _probe_token(shared_owner, connection, replacement),
        )

    assert stale == {"r": "bypass", "reason": BypassReason.METADATA_UNAVAILABLE.value}
    assert shared_owner.core.assigned_slot(namespace) is None
    assert replacement_reply is not None
    assert replacement_reply["r"] == "ok"
    assert replacement_reply["slot"] == first["slot"]
    assert shared_owner.core.assigned_slot(replacement) == tuple(first["slot"])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
@pytest.mark.parametrize("shared_owner", [{"namespaces": 1}], indirect=True)
def test_stale_metadata_probe_cannot_reregister_a_dropped_namespace(
    shared_owner: SharedCacheOwner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def allow_database(
        _owner: SharedCacheOwner, _database: str, _now: NonNegativeFloat
    ) -> None:
        return None

    monkeypatch.setattr(SharedCacheOwner, "_gate", allow_database)
    stale_namespace = NamespaceId(_DATABASE, "stale")
    active_namespace = NamespaceId(_DATABASE, "active")
    assert shared_owner.core.try_current_epoch(stale_namespace) is not None

    with socket.socket() as sock:
        connection = coordinator._Connection(sock)
        connection.session = 1
        probe = shared_owner._handle_request(
            connection,
            {
                "op": "metadata-probe",
                "ns": [stale_namespace.database, stale_namespace.collection],
            },
            time.monotonic(),
        )
        assert probe is not None
        assert probe["r"] == "probe"

        shared_owner.core.drop_namespace(stale_namespace)
        assert shared_owner.core.try_current_epoch(active_namespace) is not None
        stale_metadata = shared_owner._handle_request(
            connection,
            {
                "op": "metadata",
                "ns": [stale_namespace.database, stale_namespace.collection],
                "probe_token": probe["probe_token"],
            },
            time.monotonic(),
        )

    assert stale_metadata == {
        "r": "bypass",
        "reason": BypassReason.METADATA_UNAVAILABLE.value,
    }
    assert not shared_owner.core.has_namespace(stale_namespace)
    assert shared_owner.core.has_namespace(active_namespace)
    assert shared_owner.core.namespaces_for_database(_DATABASE) == [active_namespace]


@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
def test_metadata_cancel_releases_a_probe_reservation(
    shared_owner: SharedCacheOwner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def allow_database(
        _owner: SharedCacheOwner, _database: str, _now: NonNegativeFloat
    ) -> None:
        return None

    monkeypatch.setattr(SharedCacheOwner, "_gate", allow_database)
    abandoned = NamespaceId(_DATABASE, "abandoned")
    available = NamespaceId(_DATABASE, "available")

    with socket.socket() as sock:
        connection = coordinator._Connection(sock)
        connection.session = 1
        probe = shared_owner._handle_request(
            connection,
            {"op": "metadata-probe", "ns": list(abandoned)},
            time.monotonic(),
        )
        assert probe is not None
        assert probe["r"] == "probe"
        cancelled = shared_owner._handle_request(
            connection,
            {
                "op": "metadata-cancel",
                "ns": list(abandoned),
                "probe_token": probe["probe_token"],
            },
            time.monotonic(),
        )
        available_probe = shared_owner._handle_request(
            connection,
            {"op": "metadata-probe", "ns": list(available)},
            time.monotonic(),
        )

    assert cancelled == {"r": "ok"}
    assert available_probe is not None
    assert available_probe["r"] == "probe"
    abandoned_token = probe["probe_token"]
    assert isinstance(abandoned_token, int)
    assert (
        shared_owner.core.namespace_metadata_after_probe(abandoned, abandoned_token)
        is None
    )
    available_token = available_probe["probe_token"]
    assert isinstance(available_token, int)
    shared_owner.core.cancel_namespace_metadata_probe(available, available_token)


@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
@pytest.mark.parametrize("shared_owner", [{"namespaces": 1}], indirect=True)
def test_gate_bypass_releases_only_its_metadata_probe_request(
    shared_owner: SharedCacheOwner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate_open = True

    def toggle_database(
        _owner: SharedCacheOwner, _database: str, _now: NonNegativeFloat
    ) -> str | None:
        return None if gate_open else SharedBypassReason.STREAM_UNAVAILABLE

    monkeypatch.setattr(SharedCacheOwner, "_gate", toggle_database)
    namespace = NamespaceId(_DATABASE, "gated-probe")
    replacement = NamespaceId(_DATABASE, "after-gate-bypass")

    with socket.socket() as sock:
        connection = coordinator._Connection(sock)
        connection.session = 1
        probes = [
            shared_owner._handle_request(
                connection,
                {"op": "metadata-probe", "ns": list(namespace)},
                time.monotonic(),
            )
            for _ in range(2)
        ]
        assert all(probe is not None and probe["r"] == "probe" for probe in probes)
        first_probe, second_probe = probes
        assert first_probe is not None
        assert second_probe is not None
        assert first_probe["probe_token"] == second_probe["probe_token"]

        gate_open = False
        blocked = shared_owner._handle_request(
            connection,
            {
                "op": "metadata",
                "ns": list(namespace),
                "probe_token": first_probe["probe_token"],
            },
            time.monotonic(),
        )
        missing_token = shared_owner._handle_request(
            connection,
            {"op": "metadata", "ns": list(namespace)},
            time.monotonic(),
        )
        invalid_token = shared_owner._handle_request(
            connection,
            {"op": "metadata", "ns": list(namespace), "probe_token": True},
            time.monotonic(),
        )

        gate_open = True
        admitted = shared_owner._handle_request(
            connection,
            {
                "op": "metadata",
                "ns": list(namespace),
                "probe_token": second_probe["probe_token"],
            },
            time.monotonic(),
        )
        shared_owner.core.drop_namespace(namespace)
        replacement_probe = shared_owner._handle_request(
            connection,
            {"op": "metadata-probe", "ns": list(replacement)},
            time.monotonic(),
        )
        assert replacement_probe is not None
        assert replacement_probe["r"] == "probe"
        replacement_admission = shared_owner._handle_request(
            connection,
            {
                "op": "metadata",
                "ns": list(replacement),
                "probe_token": replacement_probe["probe_token"],
            },
            time.monotonic(),
        )

    assert blocked == {"r": "bypass", "reason": SharedBypassReason.STREAM_UNAVAILABLE}
    assert missing_token == {
        "r": "bypass",
        "reason": SharedBypassReason.STREAM_UNAVAILABLE,
    }
    assert invalid_token == {
        "r": "bypass",
        "reason": SharedBypassReason.STREAM_UNAVAILABLE,
    }
    assert admitted is not None
    assert admitted["r"] == "ok"
    assert replacement_admission is not None
    assert replacement_admission["r"] == "ok"
    assert shared_owner.core.has_namespace(replacement)


@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({}, id="missing"),
        pytest.param({"probe_token": True}, id="boolean"),
        pytest.param({"probe_token": -1}, id="negative"),
    ],
)
def test_metadata_cancel_rejects_invalid_probe_tokens(
    shared_owner: SharedCacheOwner,
    fields: dict[str, object],
) -> None:
    with socket.socket() as sock:
        connection = coordinator._Connection(sock)
        connection.session = 1
        with pytest.raises(ProtocolError, match="metadata probe token"):
            shared_owner._handle_request(
                connection,
                {"op": "metadata-cancel", "ns": [_DATABASE, "cancel"], **fields},
                time.monotonic(),
            )


@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
@pytest.mark.parametrize("shared_owner", [{"namespaces": 1}], indirect=True)
def test_drop_of_an_untracked_probe_releases_metadata_probe_capacity(
    shared_owner: SharedCacheOwner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def allow_database(
        _owner: SharedCacheOwner, _database: str, _now: NonNegativeFloat
    ) -> None:
        return None

    monkeypatch.setattr(SharedCacheOwner, "_gate", allow_database)
    stale_namespace = NamespaceId(_DATABASE, "stale-untracked")
    active_namespace = NamespaceId(_DATABASE, "active-after-drop")

    with socket.socket() as sock:
        connection = coordinator._Connection(sock)
        connection.session = 1
        probe = shared_owner._handle_request(
            connection,
            {
                "op": "metadata-probe",
                "ns": [stale_namespace.database, stale_namespace.collection],
            },
            time.monotonic(),
        )
        assert probe is not None
        assert probe["r"] == "probe"

        route_change_event(
            shared_owner.core,
            _DATABASE,
            {
                "operationType": "drop",
                "ns": {
                    "db": stale_namespace.database,
                    "coll": stale_namespace.collection,
                },
                "wallTime": dt.datetime.now(dt.UTC),
            },
        )
        stale_metadata = shared_owner._handle_request(
            connection,
            {
                "op": "metadata",
                "ns": [stale_namespace.database, stale_namespace.collection],
                "probe_token": probe["probe_token"],
            },
            time.monotonic(),
        )
        active_probe = shared_owner._handle_request(
            connection,
            {
                "op": "metadata-probe",
                "ns": [active_namespace.database, active_namespace.collection],
            },
            time.monotonic(),
        )
        assert active_probe is not None
        assert active_probe["r"] == "probe"
        active_metadata = shared_owner._handle_request(
            connection,
            {
                "op": "metadata",
                "ns": [active_namespace.database, active_namespace.collection],
                "probe_token": active_probe["probe_token"],
            },
            time.monotonic(),
        )

    assert stale_metadata == {
        "r": "bypass",
        "reason": BypassReason.METADATA_UNAVAILABLE.value,
    }
    assert active_metadata is not None
    assert active_metadata["r"] == "ok"
    assert not shared_owner.core.has_namespace(stale_namespace)
    assert shared_owner.core.has_namespace(active_namespace)
    assert shared_owner.core.namespaces_for_database(_DATABASE) == [active_namespace]


@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
@pytest.mark.parametrize("shared_owner", [{"namespaces": 2}], indirect=True)
def test_independent_concurrent_metadata_probes_can_both_be_admitted(
    shared_owner: SharedCacheOwner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def allow_database(
        _owner: SharedCacheOwner, _database: str, _now: NonNegativeFloat
    ) -> None:
        return None

    monkeypatch.setattr(SharedCacheOwner, "_gate", allow_database)
    first_namespace = NamespaceId(_DATABASE, "first-cold")
    second_namespace = NamespaceId(_DATABASE, "second-cold")

    with socket.socket() as sock:
        connection = coordinator._Connection(sock)
        connection.session = 1
        first_probe = shared_owner._handle_request(
            connection,
            {
                "op": "metadata-probe",
                "ns": [first_namespace.database, first_namespace.collection],
            },
            time.monotonic(),
        )
        second_probe = shared_owner._handle_request(
            connection,
            {
                "op": "metadata-probe",
                "ns": [second_namespace.database, second_namespace.collection],
            },
            time.monotonic(),
        )
        assert first_probe is not None
        assert first_probe["r"] == "probe"
        assert second_probe is not None
        assert second_probe["r"] == "probe"
        first_metadata = shared_owner._handle_request(
            connection,
            {
                "op": "metadata",
                "ns": [first_namespace.database, first_namespace.collection],
                "probe_token": first_probe["probe_token"],
            },
            time.monotonic(),
        )
        second_metadata = shared_owner._handle_request(
            connection,
            {
                "op": "metadata",
                "ns": [second_namespace.database, second_namespace.collection],
                "probe_token": second_probe["probe_token"],
            },
            time.monotonic(),
        )

    assert first_metadata is not None
    assert first_metadata["r"] == "ok"
    assert second_metadata is not None
    assert second_metadata["r"] == "ok"
    assert shared_owner.core.has_namespace(first_namespace)
    assert shared_owner.core.has_namespace(second_namespace)


@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({}, id="probe-token-missing"),
        pytest.param({"probe_token": True}, id="probe-token-bool"),
        pytest.param({"probe_token": -1}, id="probe-token-negative"),
    ],
)
def test_metadata_request_rejects_invalid_probe_tokens(
    shared_owner: SharedCacheOwner,
    monkeypatch: pytest.MonkeyPatch,
    fields: dict[str, object],
) -> None:
    def allow_database(
        _owner: SharedCacheOwner, _database: str, _now: NonNegativeFloat
    ) -> None:
        return None

    monkeypatch.setattr(SharedCacheOwner, "_gate", allow_database)
    request: Message = {
        "op": "metadata",
        "ns": [_DATABASE, "invalid-metadata"],
    }
    request.update(fields)
    with socket.socket() as sock:
        connection = coordinator._Connection(sock)
        connection.session = 1
        with pytest.raises(ProtocolError):
            shared_owner._handle_request(connection, request, time.monotonic())


@pytest.mark.parametrize(
    ("probe_result", "expected"),
    [
        pytest.param(None, BypassReason.METADATA_UNAVAILABLE, id="probe-failed"),
        pytest.param(
            CollectionProbeResult(BypassReason.MISSING_COLLECTION, None),
            BypassReason.MISSING_COLLECTION,
            id="missing-collection",
        ),
    ],
)
def test_metadata_uses_collection_probe_bypass_even_when_owner_admits(
    probe_result: CollectionProbeResult | None,
    expected: BypassReason,
) -> None:
    assert adapters._metadata({"r": "ok"}, probe_result) is expected


def test_metadata_reply_translates_owner_unavailability_and_capacity() -> None:
    assert adapters._metadata(None, None) == adapters.OWNER_UNAVAILABLE
    assert (
        adapters._metadata({"r": "bypass", "reason": "namespace_capacity"}, None)
        == "namespace_capacity"
    )


@pytest.mark.parametrize("token", [True, -1, "0"])
def test_metadata_probe_token_parser_rejects_invalid_values(
    token: object,
) -> None:
    with pytest.raises(ProtocolError, match="metadata probe token"):
        adapters._metadata_probe_token({"probe_token": token})


@pytest.mark.parametrize(
    "limit",
    [0, -1, 1],
    ids=["unbounded", "negative", "bounded"],
)
def test_all_complete_find_admissions_are_published(
    session: _Session, faker: Faker, limit: int
) -> None:
    reply = session.endpoint.request(_select_find(limit=limit))
    assert reply is not None
    session.endpoint.send(
        {"op": "admit", "handle": reply["handle"], "value": faker.binary(length=64)}
    )

    wait_for(lambda: session.owner.counters.admitted == 1)
    assert _index_stats(session.owner)["published"] == 1


@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
@pytest.mark.parametrize(
    "lifecycle_change", ["clear", "create"], ids=["clear", "create"]
)
def test_shared_find_admission_after_write_and_lifecycle_change_is_rejected(
    session: _Session,
    lifecycle_change: str,
) -> None:
    reply = session.endpoint.request(_select_find(epoch=session.epoch))
    assert reply is not None
    assert reply["r"] == "miss"

    session.owner.core.record_write(_NAMESPACE, "written")
    if lifecycle_change == "clear":
        session.owner.core.clear_namespace(_NAMESPACE)
    else:
        session.owner.core.create_namespace(_NAMESPACE)

    session.endpoint.send(
        {
            "op": "admit",
            "handle": reply["handle"],
            "value": encode_value({"revision": "stale"}),
        }
    )
    wait_for(lambda: not session.owner._handles)

    if session.owner.core.enable_telemetry:
        assert session.owner.core.snapshot().entry_count == 0
    assert not session.owner._handles


@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
@pytest.mark.parametrize(
    ("write", "resident"),
    [
        pytest.param(False, (True, False), id="published"),
        pytest.param(True, (False, True), id="written"),
    ],
)
def test_drained_tokens_touch_only_published_entries(
    session: _Session,
    faker: Faker,
    *,
    write: bool,
    resident: tuple[bool, bool],
) -> None:
    core = session.owner.core
    for key in (1, 2):
        session.admit(
            key,
            encode_frame(
                {"name": faker.pystr(min_chars=_ENTRY_BYTES, max_chars=_ENTRY_BYTES)}
            ),
        )
    pause_owner(session.owner, _PAUSE_SECONDS)
    time.sleep(_SWEEP_GAP_SECONDS)
    assert session.local(1) is not None
    if write:
        core.record_write(_NAMESPACE, 1)

    session.owner._drain_rings()
    for filler in range(3, 3 + _FILLERS_BEFORE_EVICTION):
        core.admit_identity(
            core.begin_identity_admission(_NAMESPACE, filler),
            _SHAPE,
            "x" * _FILLER_BYTES,
        )

    assert (
        tuple(
            core.lookup_identity_encoded(_NAMESPACE, key, _SHAPE) is not None
            for key in (1, 2)
        )
        == resident
    )


@pytest.mark.parametrize("shared_owner", [{"slots": 4}], indirect=True)
def test_publication_stops_at_the_slot_capacity(
    session: _Session, faker: Faker
) -> None:
    for key in range(1, 5):
        session.admit(key, encode_frame({"name": faker.name()}))

    assert _index_stats(session.owner)["published"] == 3
    assert session.local(4) is None


def test_every_shape_of_an_identity_is_unpublished(
    session: _Session, faker: Faker
) -> None:
    for shape in (_SHAPE, "summary"):
        capture = session.owner.core.begin_identity_admission(_NAMESPACE, 1)
        session.owner.core.admit_identity_published(
            capture,
            shape,
            encode_frame({"name": faker.name()}),
            _identity(1),
            encode_key(shape),
        )
    published = _index_stats(session.owner)["published"]

    session.owner.core.clear_namespace(_NAMESPACE)

    assert published == 2
    assert _index_stats(session.owner)["published"] == 0


def _exit_unless_detached(local: LocalIndex) -> None:
    inherited = stat.S_ISSOCK(os.fstat(local.descriptor).st_mode)
    raise SystemExit(int(not local.reader.detached or inherited))


@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
@pytest.mark.filterwarnings("ignore:This process .* is multi-threaded")
def test_forked_children_never_read_an_inherited_index(local_index: LocalIndex) -> None:
    child = multiprocessing.get_context("fork").Process(
        target=_exit_unless_detached, args=(local_index,)
    )

    child.start()
    child.join(10)

    assert child.exitcode == 0
    assert not local_index.reader.detached


@pytest.fixture
def local_miss(session: _Session, faker: Faker) -> Message:
    index = session.owner._index
    assert index is not None
    index.enable_capture(enabled=True)
    token = session.control.reader.capture(
        session.slot[0], session.slot[1], session.epoch
    )
    assert token is not None
    return {
        "op": "admit-local",
        "ns": [_DATABASE, _COLLECTION],
        "slot": session.slot,
        "epoch": session.epoch,
        "incarnation": session.owner.incarnation,
        "identity": _identity(0),
        "shape": encode_key(_SHAPE),
        "token": list(token),
        "value": encode_value({"_id": 0, "name": faker.name()}),
    }


@pytest.mark.parametrize(
    "shared_owner",
    [{}, {"local_miss_admission": True, "native_admission_queue": True}],
    indirect=True,
    ids=("socket", "native-queue"),
)
def test_a_local_miss_needs_no_owner_selection(
    session: _Session, local_miss: Message
) -> None:
    requests = session.owner.counters.requests
    session.endpoint.send(local_miss, session.control.reader)
    wait_for(lambda: session.owner.counters.admitted == 1)
    reply = session.endpoint.request({"op": "observe"})
    assert reply is not None
    assert session.owner.counters.requests == requests + 2
    assert session.owner.counters.admitted == 1
    assert session.owner.counters.misses == 0
    assert not session.owner._handles
    assert session.local(0) == local_miss["value"]


@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
@pytest.mark.parametrize(
    "shared_owner",
    [{"local_miss_admission": True, "native_admission_queue": True}],
    indirect=True,
)
def test_nonempty_admission_drains_extend_fast_polling(
    session: _Session, local_miss: Message
) -> None:
    owner = session.owner
    assert owner._admission_poll_until == 0

    session.endpoint.send(local_miss, session.control.reader)
    wait_for(lambda: owner._admission_poll_until > 0)
    first_deadline = owner._admission_poll_until
    assert first_deadline > 0

    session.endpoint.send(local_miss, session.control.reader)
    wait_for(lambda: owner._admission_poll_until > first_deadline)
    assert owner._admission_poll_until > first_deadline


@pytest.mark.parametrize(
    "shared_owner",
    [{"local_miss_admission": True, "native_admission_queue": True}],
    indirect=True,
)
@pytest.mark.parametrize(
    "frame",
    [
        b"x",
        struct.pack("<I", 1) + b"xx",
        struct.pack("<I", 1) + b"x",
        encode_frame({"v": 1, "id": 0, "op": "observe"}),
        encode_frame({"v": 1, "op": "admit-local"}),
        encode_frame({"v": 1, "id": 1, "op": "admit-local"}),
        encode_frame({"v": 1, "id": 0, "op": "admit-local"}),
    ],
    ids=(
        "short-header",
        "length-mismatch",
        "invalid-bson",
        "wrong-operation",
        "missing-id",
        "nonzero-id",
        "missing-admission-fields",
    ),
)
def test_malformed_queued_frames_detach_only_the_control_peer(
    shared_owner: SharedCacheOwner,
    writable_control: tuple[ControlAttachment, NonNegativeInt],
    endpoints: Callable[[SharedCacheOwner], SyncEndpoint],
    frame: bytes,
) -> None:
    control, _descriptor = writable_control
    assert control.reader.enqueue_admission(frame)
    wait_for(lambda: shared_owner.counters.protocol_errors == 1)
    assert control.sock.recv(1) == b""
    assert endpoints(shared_owner).request({"op": "observe"}) is not None


@pytest.mark.parametrize(
    "shared_owner",
    [{"local_miss_admission": True, "native_admission_queue": True}],
    indirect=True,
)
def test_damaged_queue_positions_detach_only_the_control_peer(
    shared_owner: SharedCacheOwner,
    writable_control: tuple[ControlAttachment, NonNegativeInt],
    endpoints: Callable[[SharedCacheOwner], SyncEndpoint],
) -> None:
    control, descriptor = writable_control
    # Native layout: four recency header words, tokens, then queue head and tail.
    tail_offset = (4 + _SHARED_INDEX.ring_tokens + 1) * 8
    os.pwrite(descriptor, struct.pack("<Q", 2**64 - 1), tail_offset)
    wait_for(lambda: shared_owner.counters.protocol_errors == 1)
    assert control.sock.recv(1) == b""
    assert endpoints(shared_owner).request({"op": "observe"}) is not None


@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
@pytest.mark.parametrize(
    "mutation",
    [
        "write",
        "reset",
        "availability",
        "progress",
        "expired",
        "future",
        "incarnation",
        "slot",
        "gate",
    ],
    ids=[
        "write",
        "reset",
        "availability",
        "progress",
        "expired",
        "future",
        "incarnation",
        "slot",
        "gate",
    ],
)
def test_obsolete_local_misses_cannot_populate_the_owner(
    session: _Session, local_miss: Message, mutation: str
) -> None:
    owner = session.owner
    assert owner._index is not None
    match mutation:
        case "write":
            owner.core.record_write(_NAMESPACE, 0)
        case "reset":
            owner.core.clear_namespace(_NAMESPACE)
        case "availability":
            owner.core.set_database_available(_DATABASE, available=False)
            owner.core.set_database_available(_DATABASE, available=True)
        case "progress":
            owner._index.set_progress(0, 1)
            owner._index.set_progress(0, time.monotonic_ns())
        case "expired" | "future":
            token = local_miss["token"]
            assert isinstance(token, list)
            token[2] = 0 if mutation == "expired" else time.monotonic_ns() + _HOUR_NS
        case "incarnation":
            local_miss["incarnation"] = owner.incarnation + 1
        case "slot":
            local_miss["slot"] = [0, 1]
        case _:
            owner.progress.observed[_DATABASE] = 0.0
    owner._admit_local(local_miss)
    if owner.config.enable_telemetry:
        assert owner.counters.rejected_admissions == 1
    if owner.core.enable_telemetry:
        assert owner.core.snapshot().entry_count == 0
    assert not owner._handles
    assert session.local(0) is None


@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
@pytest.mark.parametrize(
    "mutation", ["write", "availability"], ids=["write", "availability"]
)
def test_core_mutations_after_token_validation_prevent_local_publication(
    session: _Session,
    local_miss: Message,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    def mutate() -> None:
        if mutation == "write":
            session.owner.core.record_write(_NAMESPACE, 0)
        else:
            session.owner.core.set_database_available(_DATABASE, available=False)
            session.owner.core.set_database_available(_DATABASE, available=True)

    _racing_decode(monkeypatch, _SHAPE, Racing(_SHAPE, mutate))
    session.owner._admit_local(local_miss)
    if session.owner.config.enable_telemetry:
        assert session.owner.counters.rejected_admissions == 1
    assert session.local(0) is None


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("token", []),
        ("token", [0, 0, -1]),
        ("slot", [False, 0]),
        ("epoch", -1),
        ("incarnation", True),
        ("value", None),
    ],
    ids=(
        "token-length",
        "negative-token",
        "boolean-slot",
        "negative-epoch",
        "boolean-incarnation",
        "value-type",
    ),
)
def test_malformed_local_admissions_detach_the_peer(
    session: _Session, local_miss: Message, field: str, invalid: object
) -> None:
    local_miss[field] = invalid
    session.endpoint.send(local_miss)
    assert session.endpoint.request({"op": "observe"}) is None
    assert session.owner.counters.protocol_errors == 1
    assert not session.owner._handles


@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
def test_progress_publication_waits_for_local_admission_commit(
    session: _Session, local_miss: Message, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempted, published = threading.Event(), threading.Event()

    def publish() -> None:
        attempted.set()
        with session.owner.progress._lock:
            session.owner._publish_progress(_DATABASE, time.monotonic_ns())
        published.set()

    thread = threading.Thread(target=publish)

    def admit() -> None:
        thread.start()
        assert attempted.wait(1)
        assert not published.is_set()

    _racing_decode(monkeypatch, _SHAPE, Racing(_SHAPE, admit))
    session.owner._admit_local(local_miss)
    thread.join(1)
    assert published.is_set()
    if session.owner.config.enable_telemetry:
        assert session.owner.counters.admitted == 1


def test_local_admissions_require_shared_publication(
    owner: SharedCacheOwner,
    faker: Faker,
    endpoints: Callable[[SharedCacheOwner], SyncEndpoint],
) -> None:
    endpoint = endpoints(owner)
    endpoint.send(
        {
            "op": "admit-local",
            "ns": list(_NAMESPACE),
            "value": encode_value({"name": faker.name()}),
        }
    )
    assert endpoint.request({"op": "observe"}) is None
    assert owner.counters.protocol_errors == 1
    assert owner.core.snapshot().entry_count == 0


@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
@pytest.mark.parametrize("shared_owner", [{"namespaces": 1}], indirect=True)
def test_a_namespace_without_a_slot_cannot_admit_local_captures(
    session: _Session, local_miss: Message, faker: Faker
) -> None:
    unpublished = NamespaceId(_DATABASE, faker.pystr())
    session.owner.core.record_write(unpublished, faker.pyint())
    local_miss["ns"] = list(unpublished)
    session.owner._admit_local(local_miss)
    if session.owner.config.enable_telemetry:
        assert session.owner.counters.rejected_admissions == 1
    if session.owner.core.enable_telemetry:
        assert session.owner.core.snapshot().entry_count == 0
    assert not session.owner._handles


@pytest.fixture
def full_admission_queue(
    session: _Session, local_miss: Message
) -> Iterator[tuple[ReaderIndex, SessionRing]]:
    index = session.owner._index
    assert index is not None
    frame = encode_frame({**local_miss, "v": 1, "id": 0})
    # Fit exactly one complete record, including its native length word.
    queue_bytes = (1 + (len(frame) + 7) // 8) * 8
    ring = index.session_ring(
        4, queue_bytes, enable_telemetry=session.owner.config.enable_telemetry
    )
    descriptor = index.reader_descriptor()
    try:
        reader = ReaderIndex(
            descriptor,
            ring.descriptor(),
            enable_telemetry=session.owner.config.enable_telemetry,
        )
    finally:
        os.close(descriptor)
    assert reader.enqueue_admission(frame)
    yield reader, ring
    ring.close_descriptor()


@pytest.fixture(params=("sync", "async"))
async def admission_endpoint(
    session: _Session, request: pytest.FixtureRequest, connected: bool
) -> AsyncIterator[SyncEndpoint | AsyncEndpoint]:
    if request.param == "sync":
        if not connected:
            session.endpoint._drop()
        yield session.endpoint
    else:
        config = attachment_for(session.owner.config)
        endpoint = (
            await AsyncEndpoint.attach(config) if connected else AsyncEndpoint(config)
        )
        yield endpoint
        await endpoint.close()


@pytest.mark.parametrize("connected", [True, False], ids=("socket", "no-data-channel"))
@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
async def test_full_native_queues_use_bounded_fallback_or_skip_admission(
    session: _Session,
    local_miss: Message,
    full_admission_queue: tuple[ReaderIndex, SessionRing],
    admission_endpoint: SyncEndpoint | AsyncEndpoint,
    connected: bool,
) -> None:
    reader, ring = full_admission_queue
    admission_endpoint.send(local_miss, reader)
    if connected:
        reply = (
            await admission_endpoint.request(
                {
                    "op": "metadata-cancel",
                    "ns": [_DATABASE, _COLLECTION],
                    "probe_token": 0,
                }
            )
            if isinstance(admission_endpoint, AsyncEndpoint)
            else admission_endpoint.request(
                {
                    "op": "metadata-cancel",
                    "ns": [_DATABASE, _COLLECTION],
                    "probe_token": 0,
                }
            )
        )
        assert reply is not None
    if session.owner.config.enable_telemetry:
        assert admission_endpoint.counters.native_admissions == 0
        assert admission_endpoint.counters.native_admission_drops == int(not connected)
        assert admission_endpoint.counters.native_admission_recoveries == 0
        assert admission_endpoint.counters.one_way == int(connected)
        assert admission_endpoint.counters.dropped_one_way == int(not connected)
        assert session.owner.counters.admitted == int(connected)
    assert session.local(0) == (local_miss["value"] if connected else None)
    assert not session.owner._handles

    assert len(ring.drain_admissions()) == 1
    admission_endpoint.send(local_miss, reader)
    if session.owner.config.enable_telemetry:
        assert admission_endpoint.counters.native_admissions == 1
        assert admission_endpoint.counters.native_admission_recoveries == int(
            not connected
        )
    assert not admission_endpoint.admission_recovery.awaiting_capacity
    assert len(ring.drain_admissions()) == 1
    admission_endpoint.send(local_miss, reader)
    if session.owner.config.enable_telemetry:
        assert admission_endpoint.counters.native_admission_recoveries == int(
            not connected
        )


def _exit_unless_zero(descriptor: NonNegativeInt) -> None:
    raise SystemExit(int(os.read(descriptor, 1) != b"\x00"))


@pytest.fixture(params=["sync", "async"])
def closed_local_descriptor(
    request: pytest.FixtureRequest, shared_owner: SharedCacheOwner
) -> Iterator[NonNegativeInt]:
    with Path("/dev/zero").open("rb") as replacement:
        config = attachment_for(shared_owner.config)
        local: LocalIndex | AsyncLocalIndex
        if request.param == "sync":
            local = LocalIndex.attach(config)
            descriptor = local.descriptor
            local.close()
        else:

            async def close_async() -> tuple[AsyncLocalIndex, int]:
                local = await AsyncLocalIndex.attach(config)
                descriptor = local.descriptor
                await local.close()
                return local, descriptor

            local, descriptor = asyncio.run(close_async())
        assert descriptor >= 0
        assert local.descriptor == -1
        assert local not in attachment._LOCAL_INDEXES
        os.dup2(replacement.fileno(), descriptor)
        try:
            yield descriptor
        finally:
            os.close(descriptor)


@pytest.mark.filterwarnings("ignore:This process .* is multi-threaded")
def test_closed_attachments_do_not_replace_reused_descriptors_after_fork(
    closed_local_descriptor: NonNegativeInt,
) -> None:
    assert os.read(closed_local_descriptor, 1) == b"\x00"
    child = multiprocessing.get_context("fork").Process(
        target=_exit_unless_zero, args=(closed_local_descriptor,)
    )
    child.start()
    child.join(10)
    assert child.exitcode == 0


class _AsyncCapture(TypedDict):
    endpoint: AsyncEndpoint
    selection: Message
    handle: bytes


@pytest.fixture
async def captured_async_endpoint(
    session: _Session,
) -> AsyncIterator[_AsyncCapture]:
    endpoint = await AsyncEndpoint.attach(attachment_for(session.owner.config))
    selection: Message = {
        "op": "select-identity",
        "ns": [_DATABASE, _COLLECTION],
        "epoch": session.epoch,
        "identity": _identity(1),
        "shape": encode_key(_SHAPE),
    }
    try:
        reply = await endpoint.request(selection)
        assert reply is not None
        assert isinstance(reply["handle"], bytes)
        yield {"endpoint": endpoint, "selection": selection, "handle": reply["handle"]}
    finally:
        await endpoint.close()


@pytest.mark.parametrize("operation", ["discard", "admit"], ids=["discard", "admit"])
async def test_saturated_capture_messages_release_owner_reservations(
    session: _Session,
    captured_async_endpoint: _AsyncCapture,
    operation: Literal["discard", "admit"],
) -> None:
    endpoint = captured_async_endpoint["endpoint"]
    writer = endpoint._writer
    assert writer is not None
    writer.get_extra_info("socket").setsockopt(
        socket.SOL_SOCKET, socket.SO_SNDBUF, 4096
    )
    pause_owner(session.owner, _PAUSE_SECONDS)
    pending = asyncio.create_task(endpoint.request({"op": "observe"}))
    await asyncio.sleep(0)
    filler = encode_frame(
        {
            "v": PROTOCOL_VERSION,
            "id": 0,
            "op": "observe",
            "padding": bytes(endpoint.config.frame_limit // 2),
        }
    )
    for _ in range(4):
        writer.write(filler)
    assert writer.transport.get_write_buffer_size() > endpoint.config.frame_limit

    endpoint.send(
        {
            "op": operation,
            "handle": captured_async_endpoint["handle"],
            "value": b"value",
        }
    )

    assert endpoint._writer is None
    assert writer.transport.get_write_buffer_size() == 0
    assert await pending is None
    await asyncio.to_thread(wait_for, lambda: not session.owner._handles)
    replacement = await endpoint.request(captured_async_endpoint["selection"])
    assert replacement is not None
    assert isinstance(replacement["handle"], bytes)
    endpoint.send({"op": "discard", "handle": replacement["handle"]})
    await asyncio.to_thread(wait_for, lambda: not session.owner._handles)


@pytest.fixture(params=[False, True], ids=["watching", "watcher-finished"])
async def async_local_to_close(
    shared_owner: SharedCacheOwner, request: pytest.FixtureRequest
) -> AsyncIterator[AsyncLocalIndex]:
    local = await AsyncLocalIndex.attach(attachment_for(shared_owner.config))
    try:
        if request.param:
            local._sock.shutdown(socket.SHUT_RD)
            await local._watcher
        else:
            assert not local._watcher.done()
        yield local
    finally:
        await local.close()


async def test_async_local_close_releases_descriptor_before_returning(
    async_local_to_close: AsyncLocalIndex,
) -> None:
    await async_local_to_close.close()

    assert async_local_to_close.descriptor == -1
    assert async_local_to_close not in attachment._LOCAL_INDEXES


@pytest.fixture
def local_waiting_to_close(
    shared_owner: SharedCacheOwner, monkeypatch: pytest.MonkeyPatch
) -> Iterator[LocalIndex]:
    local = LocalIndex.attach(attachment_for(shared_owner.config))
    joining, resume = threading.Event(), threading.Event()
    join = local._watcher.join

    def held_join() -> None:
        joining.set()
        assert resume.wait(10)
        join()

    monkeypatch.setattr(local._watcher, "join", held_join)
    closer = threading.Thread(target=local.close)
    closer.start()
    try:
        assert joining.wait(10)
        yield local
    finally:
        resume.set()
        closer.join(10)
        assert not closer.is_alive()


@pytest.mark.filterwarnings("ignore:This process .* is multi-threaded")
def test_fork_during_sync_close_detaches_the_still_open_socket(
    local_waiting_to_close: LocalIndex,
) -> None:
    assert local_waiting_to_close.descriptor >= 0
    child = multiprocessing.get_context("fork").Process(
        target=_exit_unless_detached, args=(local_waiting_to_close,)
    )
    child.start()
    child.join(10)
    assert child.exitcode == 0


@pytest.mark.parametrize(
    "owner_telemetry", [False, True], indirect=True, ids=["disabled", "enabled"]
)
def test_interrupted_sync_join_closes_and_unregisters_the_socket(
    local_index: LocalIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    join = local_index._watcher.join

    def interrupted_join() -> None:
        join()
        raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr(local_index._watcher, "join", interrupted_join)
        with pytest.raises(KeyboardInterrupt):
            local_index.close()

    assert local_index.descriptor == -1
    assert local_index not in attachment._LOCAL_INDEXES
