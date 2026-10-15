from __future__ import annotations

import asyncio
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
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from benchmarks.stream_cost.shared_cache.window import attachment_for
from client_query_cache._core.canonical import canonicalize
from client_query_cache._core.codec import encode_value
from client_query_cache._core.keys import IdentityCacheKey, NamespaceId
from client_query_cache._core.lru import WeightedLru
from client_query_cache._core.manager import CacheCore, IdentityCapture
from client_query_cache._core.order_sensitive_keys import order_sensitive_key
from client_query_cache._shared import coordinator
from client_query_cache._shared.attachment import (
    AsyncEndpoint,
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
from client_query_cache._shared.shared_index import SharedIndexLimits
from client_query_cache._shared.wire import (
    decode_frame,
    encode_frame,
    encode_key,
)
from client_query_cache._shared_index import Payload, ReaderIndex
from client_query_cache._types import NonNegativeFloat, NonNegativeInt, PositiveFloat
from tests.core.conftest import patch_conditional_put_hook
from tests.shared_cache.conftest import LIMITS, wait_for

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator
    from multiprocessing.connection import Connection

    from faker import Faker

    from client_query_cache._core.entries import AdmissionOutcome
    from client_query_cache._shared.attachment import Message

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
_SHARED_INDEX = SharedIndexLimits(
    slots=64, arena_bytes=1024 * 1024, namespaces=4, ring_tokens=64
)
_HOUR_NS = 3_600 * 10**9
_PARTIAL_SEND_BYTES = 5
_SMALL_RING = 4
_OVERFLOWING_HITS = 32
_ADDRESS_MASK = 0xFFFF_FFFF
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
    )
    return replace(config, **changes)  # type: ignore[arg-type]


def _serving(config: OwnerConfig) -> Iterator[SharedCacheOwner]:
    instance = SharedCacheOwner(config)
    instance.bind()
    parent, child = multiprocessing.Pipe()
    serving = threading.Thread(
        target=instance.serve, args=(child, lambda _request: {"ok": True})
    )
    serving.start()
    yield instance
    parent.send("close")
    serving.join(10)
    instance.close()


@pytest.fixture
def owner(
    socket_directory: Path, request: pytest.FixtureRequest
) -> Iterator[SharedCacheOwner]:
    limits = getattr(request, "param", {})
    yield from _serving(_config(socket_directory, limits=replace(LIMITS, **limits)))


@pytest.fixture
def shared_owner(
    socket_directory: Path, request: pytest.FixtureRequest
) -> Iterator[SharedCacheOwner]:
    changes = getattr(request, "param", {})
    yield from _serving(
        _config(
            socket_directory,
            budget_bytes=_SHARED_BUDGET,
            max_entry_bytes=_SHARED_MAX_ENTRY,
            shared_index=replace(_SHARED_INDEX, **changes),
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
    socket_directory: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[_PollingLoop]:
    instance = SharedCacheOwner(
        _config(
            socket_directory,
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


def test_recent_admissions_poll_without_accelerating_maintenance(
    polling_loop: _PollingLoop,
) -> None:
    polling_loop.owner.serve(polling_loop.control, lambda _request: None)

    assert polling_loop.timeouts == pytest.approx([0.005] * 10 + [0.05] * 2)
    assert polling_loop.sweeps == pytest.approx([0.005, 0.1])
    assert polling_loop.drains == pytest.approx(
        [milliseconds / 1000 for milliseconds in range(5, 51, 5)] + [0.1]
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
    assert owner.counters.unauthorized == 1
    monkeypatch.setattr(os, "geteuid", original_uid)
    assert endpoints(owner).request({"op": "observe"}) is not None


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
        reader = ReaderIndex(*descriptors)
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
    return endpoint.request({"op": "metadata", "ns": [_DATABASE, "catalogue"]})


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
    assert first["reason"] == held["reason"] == "stream-starting"


def test_a_second_owner_cannot_bind_a_held_endpoint(
    contender: SharedCacheOwner,
) -> None:
    with pytest.raises(RuntimeError, match="already holds this endpoint"):
        contender.bind()


def test_a_peer_that_disappears_before_its_reply_is_detached(
    owner: SharedCacheOwner,
) -> None:
    peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    peer.connect(owner.config.socket_path)
    peer.sendall(encode_frame(attachment_for(owner.config).hello()))
    peer.close()

    wait_for(
        lambda: owner.counters.connections_accepted == 1 and not owner._connections
    )


def _activate(owner: SharedCacheOwner) -> None:
    owner._activation[_DATABASE] = ("active", time.monotonic())
    owner.progress.observed[_DATABASE] = time.monotonic() + 3600


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


def test_selection_reports_unavailable_streams_and_stale_epochs(
    owner: SharedCacheOwner, endpoints: Callable[[SharedCacheOwner], SyncEndpoint]
) -> None:
    _activate(owner)
    endpoint = endpoints(owner)

    stale = endpoint.request(_select_find(epoch=7))
    owner.core.set_database_available(_DATABASE, available=False)
    unavailable = endpoint.request(_select_find())

    assert stale is not None
    assert stale["r"] == "refresh"
    assert unavailable is not None
    assert unavailable["reason"] == "stream-unavailable"


@pytest.mark.parametrize(
    "message",
    [
        pytest.param(_select_find(limit="four"), id="find-limit"),
        pytest.param({"op": "rename", "ns": [_DATABASE, "catalogue"]}, id="operation"),
    ],
)
def test_invalid_requests_after_the_gate_detach_the_peer(
    owner: SharedCacheOwner,
    peers: Callable[[SharedCacheOwner], socket.socket],
    message: Message,
) -> None:
    _activate(owner)
    peer = peers(owner)

    peer.sendall(encode_frame({"v": 1, "id": 2, **message}))

    assert peer.recv(1) == b""
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


@pytest.mark.parametrize("owner", [{"capture_seconds": 0.2}], indirect=True)
def test_capture_expiry_releases_handles_of_each_session(
    owner: SharedCacheOwner, endpoints: Callable[[SharedCacheOwner], SyncEndpoint]
) -> None:
    _activate(owner)
    sessions = [endpoints(owner) for _ in range(2)]

    replies = [endpoint.request(_select_find()) for endpoint in sessions]
    wait_for(lambda: owner.counters.expired_captures == 2)

    assert all(reply is not None and reply["r"] == "miss" for reply in replies)
    assert not owner._handles


def test_a_reply_larger_than_the_send_buffer_is_flushed_in_parts(
    owner: SharedCacheOwner,
    peers: Callable[[SharedCacheOwner], socket.socket],
    faker: Faker,
) -> None:
    _activate(owner)
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


def test_a_reply_delivered_after_its_deadline_is_counted_as_late(
    owner: SharedCacheOwner,
) -> None:
    config = replace(
        attachment_for(owner.config), rpc_deadline_seconds=_RPC_DEADLINE_SECONDS
    )

    async def scenario() -> tuple[Message | None, EndpointCounters]:
        endpoint = await AsyncEndpoint.attach(config)
        sent = owner.counters.ipc_bytes_sent
        expiry = time.monotonic() + _RPC_DEADLINE_SECONDS
        request = asyncio.create_task(endpoint.request({"op": "observe"}))
        await asyncio.sleep(0)
        wait_for(
            lambda: owner.counters.ipc_bytes_sent > sent and time.monotonic() > expiry
        )
        reply = await request
        await endpoint.close()
        return reply, endpoint.counters

    reply, counters = asyncio.run(scenario())

    assert reply is None
    assert counters.timeouts == 1
    assert counters.late_replies == 1


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
        processed = self.owner.counters.admissions
        reply = self.select(key)
        assert reply["r"] == "miss"
        self.endpoint.send({"op": "admit", "handle": reply["handle"], "value": value})
        wait_for(lambda: self.owner.counters.admissions > processed)

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


def _rolled_back(session: _Session, value: bytes, patch: pytest.MonkeyPatch) -> None:
    def write(_key: object, _entry: object) -> None:
        session.owner.core.record_write(_NAMESPACE, 1)

    patch_conditional_put_hook(patch, session.owner.core, write)
    session.admit(1, value)


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


def test_an_rpc_hit_never_returns_a_reused_block(
    session: _Session, faker: Faker, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = encode_frame({"name": faker.name()})
    session.admit(1, value)
    core = session.owner.core
    index = session.owner._index
    assert index is not None
    key = IdentityCacheKey(
        _NAMESPACE, canonicalize(order_sensitive_key(1)), canonicalize(_SHAPE)
    )
    entry = core._lru.peek(key)
    assert entry is not None
    original = entry.value
    assert isinstance(original, Payload)
    reused: list[Payload | None] = []
    touch = WeightedLru.touch

    def evict_and_reuse(lru: WeightedLru, touched: object) -> None:
        for filler in range(2, 2 + _FILLERS):
            capture = core.begin_identity_admission(_NAMESPACE, filler)
            core.admit_identity_encoded(capture, _SHAPE, b"x" * _FILLER_BYTES)
        reused.append(index.store(faker.binary(length=len(value))))
        touch(lru, touched)  # type: ignore[arg-type]

    monkeypatch.setattr(WeightedLru, "touch", evict_and_reuse)

    reply = session.select(1)

    assert core._lru.peek(key) is None
    assert reused[0] is not None
    assert reused[0].token & _ADDRESS_MASK == original.token & _ADDRESS_MASK
    assert reply["r"] == "miss" or reply["value"] == value


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
    # Count descriptors before the failed handshake can leak them.
    before = _open_descriptors()  # pytriage: TR11
    peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    peer.connect(shared_owner.config.socket_path)
    peer.sendall(encode_frame(attachment_for(shared_owner.config).hello("control")))
    wait_for(lambda: _pending_handover(shared_owner))
    peer.close()

    wait_for(lambda: not shared_owner._connections)
    assert _open_descriptors() <= before
    assert _index_stats(shared_owner)["sessions"] == 0


def _open_descriptors() -> set[str]:
    return {entry.name for entry in Path("/proc/self/fd").iterdir()}


def _pending_handover(owner: SharedCacheOwner) -> bool:
    return any(
        connection.handover is not None for connection in owner._connections.values()
    )


@pytest.mark.parametrize("shared_owner", [{"namespaces": 1}], indirect=True)
def test_namespaces_beyond_the_slot_capacity_stay_unpublished(
    session: _Session, faker: Faker
) -> None:
    other = NamespaceId(_DATABASE, "other")
    metadata = session.endpoint.request({"op": "metadata", "ns": list(other)})
    assert metadata is not None
    reply = session.endpoint.request(
        {
            "op": "select-identity",
            "ns": list(other),
            "epoch": metadata["epoch"],
            "identity": _identity(1),
            "shape": encode_key(_SHAPE),
        }
    )
    assert reply is not None
    session.endpoint.send(
        {
            "op": "admit",
            "handle": reply["handle"],
            "value": encode_frame({"name": faker.name()}),
        }
    )
    wait_for(lambda: session.owner.counters.admitted == 1)
    session.owner.core.clear_namespace(other)

    assert "slot" not in metadata
    assert _index_stats(session.owner)["published"] == 0


def test_find_admissions_are_not_published(session: _Session, faker: Faker) -> None:
    reply = session.endpoint.request(_select_find())
    assert reply is not None
    session.endpoint.send(
        {"op": "admit", "handle": reply["handle"], "value": faker.binary(length=64)}
    )

    wait_for(lambda: session.owner.counters.admitted == 1)
    assert _index_stats(session.owner)["published"] == 0


@pytest.mark.parametrize(
    ("write", "most_recent"),
    [pytest.param(False, 1, id="published"), pytest.param(True, 2, id="written")],
)
def test_drained_tokens_touch_only_published_entries(
    session: _Session, faker: Faker, *, write: bool, most_recent: int
) -> None:
    for key in (1, 2):
        session.admit(key, encode_frame({"name": faker.name()}))
    publisher = session.owner._publisher
    assert publisher is not None
    session.owner.pause(_PAUSE_SECONDS)
    time.sleep(_SWEEP_GAP_SECONDS)
    assert session.local(1) is not None
    if write:
        session.owner.core.record_write(_NAMESPACE, 1)

    session.owner._drain_rings(publisher)

    newest = list(session.owner.core._lru._order)[-1]
    assert isinstance(newest, IdentityCacheKey)
    assert newest.identity == canonicalize(order_sensitive_key(most_recent))


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
        session.owner.core.admit_identity_encoded(
            capture, shape, encode_frame({"name": faker.name()})
        )
    published = _index_stats(session.owner)["published"]

    session.owner.core.clear_namespace(_NAMESPACE)

    assert published == 2
    assert _index_stats(session.owner)["published"] == 0


def _exit_unless_detached(local: LocalIndex) -> None:
    inherited = stat.S_ISSOCK(os.fstat(local.descriptor).st_mode)
    raise SystemExit(int(not local.reader.detached or inherited))


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
    wait_for(lambda: owner.counters.admissions == 1)
    first_deadline = owner._admission_poll_until
    assert first_deadline > 0

    session.endpoint.send(local_miss, session.control.reader)
    wait_for(lambda: owner.counters.admissions == 2)
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
            assert not owner.core._namespaces[_NAMESPACE].identities
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
    assert owner.counters.rejected_admissions == 1
    assert owner.core.snapshot().entry_count == 0
    assert not owner._handles
    assert not owner.core._namespaces[_NAMESPACE].identities
    assert session.local(0) is None


@pytest.mark.parametrize(
    "mutation", ["write", "availability"], ids=["write", "availability"]
)
def test_core_mutations_after_token_validation_prevent_local_publication(
    session: _Session,
    local_miss: Message,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    original = CacheCore.admit_identity_encoded

    def mutate(
        core: CacheCore, capture: IdentityCapture, shape: object, encoded: bytes
    ) -> AdmissionOutcome:
        if mutation == "write":
            session.owner.core.record_write(_NAMESPACE, 0)
        else:
            session.owner.core.set_database_available(_DATABASE, available=False)
            session.owner.core.set_database_available(_DATABASE, available=True)
        return original(core, capture, shape, encoded)

    monkeypatch.setattr(CacheCore, "admit_identity_encoded", mutate)
    session.owner._admit_local(local_miss)
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


def test_progress_publication_waits_for_local_admission_commit(
    session: _Session, local_miss: Message, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempted, published = threading.Event(), threading.Event()

    def publish() -> None:
        attempted.set()
        with session.owner.progress._lock:
            assert session.owner._publisher is not None
            session.owner._publisher.progress(_DATABASE)
        published.set()

    thread = threading.Thread(target=publish)
    original = CacheCore.admit_identity_encoded

    def admit(
        core: CacheCore, capture: IdentityCapture, shape: object, encoded: bytes
    ) -> AdmissionOutcome:
        thread.start()
        assert attempted.wait(1)
        assert not published.is_set()
        return original(core, capture, shape, encoded)

    monkeypatch.setattr(CacheCore, "admit_identity_encoded", admit)
    session.owner._admit_local(local_miss)
    thread.join(1)
    assert published.is_set()
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


@pytest.mark.parametrize("shared_owner", [{"namespaces": 1}], indirect=True)
def test_a_namespace_without_a_slot_cannot_admit_local_captures(
    session: _Session, local_miss: Message, faker: Faker
) -> None:
    unpublished = NamespaceId(_DATABASE, faker.pystr())
    session.owner.core.record_write(unpublished, faker.pyint())
    local_miss["ns"] = list(unpublished)
    session.owner._admit_local(local_miss)
    assert session.owner.counters.rejected_admissions == 1
    assert session.owner.core.snapshot().entry_count == 0
    assert not session.owner._handles


@pytest.fixture
def full_admission_queue(
    session: _Session, local_miss: Message
) -> Iterator[ReaderIndex]:
    index = session.owner._index
    assert index is not None
    frame = encode_frame({**local_miss, "v": 1, "id": 0})
    # Fit exactly one complete record, including its native length word.
    queue_bytes = (1 + (len(frame) + 7) // 8) * 8
    ring = index.session_ring(4, queue_bytes)
    descriptor = index.reader_descriptor()
    try:
        reader = ReaderIndex(descriptor, ring.descriptor())
    finally:
        os.close(descriptor)
    assert reader.enqueue_admission(frame)
    yield reader
    ring.close_descriptor()


@pytest.fixture(params=("sync", "async"))
async def admission_endpoint(
    session: _Session, request: pytest.FixtureRequest
) -> AsyncIterator[SyncEndpoint | AsyncEndpoint]:
    if request.param == "sync":
        yield session.endpoint
    else:
        endpoint = AsyncEndpoint(attachment_for(session.owner.config))
        assert await endpoint.request({"op": "observe"}) is not None
        yield endpoint
        await endpoint.close()


async def test_full_native_queues_fall_back_to_socket_admission(
    session: _Session,
    local_miss: Message,
    full_admission_queue: ReaderIndex,
    admission_endpoint: SyncEndpoint | AsyncEndpoint,
) -> None:
    admission_endpoint.send(local_miss, full_admission_queue)
    reply = (
        await admission_endpoint.request({"op": "observe"})
        if isinstance(admission_endpoint, AsyncEndpoint)
        else admission_endpoint.request({"op": "observe"})
    )
    assert reply is not None
    assert admission_endpoint.counters.native_admissions == 0
    assert admission_endpoint.counters.one_way == 1
    assert session.owner.counters.admitted == 1
    assert session.local(0) == local_miss["value"]
    assert not session.owner._handles
