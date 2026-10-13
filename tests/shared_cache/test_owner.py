from __future__ import annotations

import asyncio
import multiprocessing
import os
import secrets
import select
import socket
import stat
import struct
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from client_query_cache_shared_index import Payload

from benchmarks.stream_cost.shared_cache.attachment import (
    AsyncEndpoint,
    AttachmentConfigurationError,
    ControlAttachment,
    EndpointCounters,
    LocalIndex,
    SyncEndpoint,
    control_handshake,
)
from benchmarks.stream_cost.shared_cache.coordinator import (
    OwnerConfig,
    SharedCacheOwner,
)
from benchmarks.stream_cost.shared_cache.shared_index import SharedIndexLimits
from benchmarks.stream_cost.shared_cache.window import attachment_for
from benchmarks.stream_cost.shared_cache.wire import (
    decode_frame,
    encode_frame,
    encode_key,
)
from client_query_cache._core.canonical import canonicalize
from client_query_cache._core.keys import IdentityCacheKey, NamespaceId
from client_query_cache._core.lru import WeightedLru
from client_query_cache._core.order_sensitive_keys import order_sensitive_key
from tests.core.conftest import patch_conditional_put_hook
from tests.shared_cache.conftest import LIMITS, wait_for

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from faker import Faker

    from benchmarks.stream_cost.shared_cache.attachment import Message

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
