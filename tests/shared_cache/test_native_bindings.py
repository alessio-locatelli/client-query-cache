from __future__ import annotations

import multiprocessing
import os
import resource
import socket
import struct
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, monotonic_ns
from typing import TYPE_CHECKING, Literal

import pytest

from benchmarks.stream_cost.multiprocess_run import reclaim_workers
from client_query_cache._shared_index import ByteRelay, OwnerIndex, ReaderIndex
from client_query_cache._types import NonEmptyStr, NonNegativeInt, PositiveInt

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterator
    from concurrent.futures import Future
    from multiprocessing.process import BaseProcess

    from faker import Faker

    from client_query_cache._shared_index import SessionRing

type DescriptorOperation = Literal["owner", "ring", "descriptor", "echo"]

pytestmark = pytest.mark.unit

_INCARNATION = 41
_EPOCH = 7
_EXPIRY_NS = 60 * 10**9
_USIZE_MAX = 2 * sys.maxsize + 1


@pytest.fixture
def native_owner() -> OwnerIndex:
    owner = OwnerIndex(8, 4096, 1, 1, _INCARNATION, _EXPIRY_NS)
    owner.set_available(0, available=True)
    owner.set_progress(0, monotonic_ns())
    owner.set_epoch(0, _EPOCH)
    owner.enable_capture(enabled=True)
    return owner


@pytest.fixture
def index_descriptor(native_owner: OwnerIndex) -> Iterator[NonNegativeInt]:
    descriptor = native_owner.reader_descriptor()
    yield descriptor
    os.close(descriptor)


@pytest.fixture
def open_ring(
    native_owner: OwnerIndex,
) -> Iterator[Callable[[PositiveInt, NonNegativeInt], SessionRing]]:
    with ExitStack() as resources:

        def create(tokens: PositiveInt, admission_bytes: NonNegativeInt) -> SessionRing:
            ring = native_owner.session_ring(tokens, admission_bytes)
            resources.callback(ring.close_descriptor)
            return ring

        yield create


@pytest.fixture
def native_ring(
    open_ring: Callable[[PositiveInt, NonNegativeInt], SessionRing],
) -> SessionRing:
    return open_ring(8, 64)


@pytest.fixture
def native_reader(
    index_descriptor: NonNegativeInt, native_ring: SessionRing
) -> ReaderIndex:
    return ReaderIndex(index_descriptor, native_ring.descriptor())


@pytest.fixture
def mapped_descriptor() -> Iterator[Callable[[bytes], NonNegativeInt]]:
    with ExitStack() as resources:

        def create(contents: bytes) -> NonNegativeInt:
            descriptor = os.memfd_create("native-binding-test")
            resources.callback(os.close, descriptor)
            os.write(descriptor, contents)
            return descriptor

        yield create


@pytest.mark.parametrize(
    "layout",
    [
        (0, 4096, 1, 1),
        (3, 4096, 1, 1),
        (8, 0, 1, 1),
        (8, 4096, 0, 1),
        (8, 4096, 1, 0),
        (8, 1 << 35, 1, 1),
        (8, 4096, 1, 1 << 32),
        (8, 4096, _USIZE_MAX, 1),
        (1 << 63, 4096, 1, 1),
    ],
    ids=(
        "zero-slots",
        "non-power-of-two",
        "zero-arena",
        "zero-databases",
        "zero-namespaces",
        "arena-overflow",
        "namespace-overflow",
        "layout-overflow",
        "slot-overflow",
    ),
)
def test_rejects_invalid_layout(
    layout: tuple[NonNegativeInt, NonNegativeInt, NonNegativeInt, NonNegativeInt],
) -> None:
    with pytest.raises(ValueError, match="invalid index layout"):
        OwnerIndex(*layout, _INCARNATION, _EXPIRY_NS)


@pytest.mark.parametrize(
    "operation",
    [
        lambda owner: owner.set_available(1, available=True),
        lambda owner: owner.set_progress(1, monotonic_ns()),
        lambda owner: owner.set_epoch(1, _EPOCH),
        lambda owner: owner.record_write(1),
    ],
    ids=("available", "progress", "epoch", "write"),
)
def test_rejects_out_of_range_updates(
    native_owner: OwnerIndex,
    operation: Callable[[OwnerIndex], None],
) -> None:
    with pytest.raises(ValueError, match="outside the index layout"):
        operation(native_owner)


@pytest.mark.parametrize(
    ("tokens", "admission_bytes", "message"),
    [
        (0, 0, "invalid ring capacity"),
        (_USIZE_MAX, 0, "invalid ring capacity"),
        (8, 8, "invalid admission capacity"),
        (_USIZE_MAX - 4, 64, "invalid admission capacity"),
    ],
    ids=("zero-tokens", "ring-overflow", "small-admission-queue", "combined-overflow"),
)
def test_rejects_invalid_ring_capacity(
    native_owner: OwnerIndex,
    tokens: NonNegativeInt,
    admission_bytes: NonNegativeInt,
    message: NonEmptyStr,
) -> None:
    with pytest.raises(ValueError, match=message):
        native_owner.session_ring(tokens, admission_bytes)


@pytest.mark.parametrize("invalid_index", [True, False], ids=("index", "ring"))
def test_rejects_negative_descriptors(
    index_descriptor: NonNegativeInt,
    native_ring: SessionRing,
    invalid_index: bool,
) -> None:
    with pytest.raises(ValueError, match="descriptors must be non-negative"):
        ReaderIndex(
            -1 if invalid_index else index_descriptor,
            native_ring.descriptor() if invalid_index else -1,
        )


@pytest.mark.parametrize(
    ("target", "contents", "exception", "message"),
    [
        ("index", b"", OSError, "invalid data"),
        ("index", bytes(7), OSError, "invalid data"),
        ("index", bytes(128), ValueError, "holds no index"),
        ("ring", bytes(32), ValueError, "holds no ring"),
    ],
    ids=("empty", "unaligned", "invalid-index", "invalid-ring"),
)
def test_rejects_invalid_descriptor_contents(
    *,
    index_descriptor: NonNegativeInt,
    native_ring: SessionRing,
    mapped_descriptor: Callable[[bytes], NonNegativeInt],
    target: Literal["index", "ring"],
    contents: bytes,
    exception: type[Exception],
    message: NonEmptyStr,
) -> None:
    invalid = mapped_descriptor(contents)
    with pytest.raises(exception, match=message):
        ReaderIndex(
            invalid if target == "index" else index_descriptor,
            native_ring.descriptor() if target == "index" else invalid,
        )


def test_rejects_an_incomplete_admission_queue(
    index_descriptor: NonNegativeInt,
    open_ring: Callable[[PositiveInt, NonNegativeInt], SessionRing],
    mapped_descriptor: Callable[[bytes], NonNegativeInt],
) -> None:
    ring = open_ring(8, 0)
    contents = os.pread(ring.descriptor(), os.fstat(ring.descriptor()).st_size, 0)
    with pytest.raises(ValueError, match="holds no admission queue"):
        ReaderIndex(index_descriptor, mapped_descriptor(contents + bytes(8)))


def test_ring_descriptor_close_is_idempotent(native_ring: SessionRing) -> None:
    native_ring.close_descriptor()
    native_ring.close_descriptor()
    with pytest.raises(ValueError, match="ring descriptor is closed"):
        native_ring.descriptor()


def test_detached_reader_never_reads_or_enqueues(native_reader: ReaderIndex) -> None:
    assert native_reader.incarnation == _INCARNATION
    assert native_reader.admissions_enabled
    assert (native_reader.detached,) == (False,)
    assert native_reader.capture(0, 0, _EPOCH) is not None
    native_reader.detach()
    native_reader.detach()
    assert native_reader.detached
    assert native_reader.lookup(0, 0, _EPOCH, b"identity", b"shape") is None
    assert native_reader.capture(0, 0, _EPOCH) is None
    assert not native_reader.enqueue_admission(b"frame")


def test_ring_without_admissions_reports_an_empty_queue(
    open_ring: Callable[[PositiveInt, NonNegativeInt], SessionRing],
    index_descriptor: NonNegativeInt,
) -> None:
    ring = open_ring(8, 0)
    reader = ReaderIndex(index_descriptor, ring.descriptor())
    assert not reader.admissions_enabled
    assert not reader.enqueue_admission(b"frame")
    assert ring.drain_admissions() == []


@pytest.mark.parametrize(
    "identity_bytes",
    [0, 507, 508, 1024],
    ids=("empty-identity", "inline-key-limit", "spilled-key", "long-key"),
)
def test_payload_tokens_identify_reads_and_release(
    native_owner: OwnerIndex,
    native_reader: ReaderIndex,
    native_ring: SessionRing,
    faker: Faker,
    identity_bytes: NonNegativeInt,
) -> None:
    identity = faker.binary(length=identity_bytes)
    expected = faker.binary(length=32)
    payload = native_owner.store(expected)
    assert payload is not None
    assert native_owner.snapshot(payload) == expected
    assert (
        native_owner.publish(0, 0, _EPOCH, identity, b"shape", payload) == payload.token
    )
    assert native_owner.published() == 1
    assert native_reader.lookup(0, 0, _EPOCH, identity, b"shape") == expected
    assert native_ring.drain() == [payload.token]
    native_owner.release(payload)
    native_owner.release(payload)
    assert native_owner.snapshot(payload) is None
    assert native_owner.published() == 0
    assert native_reader.lookup(0, 0, _EPOCH, identity, b"shape") is None


@pytest.fixture
def native_echo(native_owner: OwnerIndex, tmp_path: Path) -> Iterator[socket.socket]:
    path = tmp_path / "echo.sock"
    echo = native_owner.serve(str(path))
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(3)
        client.connect(str(path))
        yield client
    echo.close()
    echo.close()


def test_echo_preserves_request_id_for_empty_selection(
    native_echo: socket.socket,
) -> None:
    request_id = 71
    frame = struct.pack("<III", 8, request_id, 0)
    native_echo.sendall(frame[:3])
    native_echo.sendall(frame[3:])
    with native_echo.makefile("rb") as replies:
        assert replies.read(len(frame)) == frame


@pytest.fixture
def native_relay() -> Iterator[
    tuple[ByteRelay, socket.socket, socket.socket, Future[None]]
]:
    relay = ByteRelay()
    with ThreadPoolExecutor(max_workers=1) as executor, ExitStack() as resources:
        listener = resources.enter_context(
            socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        )
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        client = resources.enter_context(
            socket.create_connection(listener.getsockname())
        )
        incoming = resources.enter_context(listener.accept()[0])
        outgoing = resources.enter_context(
            socket.create_connection(listener.getsockname())
        )
        server = resources.enter_context(listener.accept()[0])
        client.settimeout(3)
        server.settimeout(3)
        forwarding = executor.submit(relay.run, incoming.fileno(), outgoing.fileno())
        yield relay, client, server, forwarding
        relay.stop()


def test_relay_preserves_both_half_closes_and_counts_bytes(
    native_relay: tuple[ByteRelay, socket.socket, socket.socket, Future[None]],
    faker: Faker,
) -> None:
    relay, client, server, forwarding = native_relay
    request = faker.binary(length=32)
    relay.pause()
    assert relay.bytes_sent == 0
    assert relay.bytes_received == 0
    relay.resume()
    client.sendall(request)
    client.shutdown(socket.SHUT_WR)
    with server.makefile("rb") as requests:
        assert requests.read() == request
    reply = faker.binary(length=64)
    server.sendall(reply)
    server.shutdown(socket.SHUT_WR)
    with client.makefile("rb") as replies:
        assert replies.read() == reply
    forwarding.result(timeout=3)
    assert relay.bytes_sent == len(request)
    assert relay.bytes_received == len(reply)


@pytest.mark.parametrize("descriptor", [-1, 2**31 - 1], ids=("negative", "invalid"))
def test_relay_rejects_invalid_descriptors(descriptor: int) -> None:
    with pytest.raises(OSError, match="Bad file descriptor"):
        ByteRelay().run(descriptor, descriptor)


def test_echo_reports_missing_parent_directory(
    native_owner: OwnerIndex, tmp_path: Path
) -> None:
    with pytest.raises(FileNotFoundError, match="No such file or directory"):
        native_owner.serve(str(tmp_path / "missing" / "echo.sock"))


def test_damaged_admission_queue_reports_a_binding_error(
    native_ring: SessionRing,
    open_ring: Callable[[PositiveInt, NonNegativeInt], SessionRing],
) -> None:
    queue_start = os.fstat(open_ring(8, 0).descriptor()).st_size
    # Publish one word whose frame length is still zero, as in a damaged peer queue.
    os.pwrite(native_ring.descriptor(), struct.pack("<QQ", 0, 1), queue_start)
    with pytest.raises(ValueError, match="damaged admission queue"):
        native_ring.drain_admissions()


def test_echo_closes_a_connection_with_an_oversized_frame(
    native_echo: socket.socket,
) -> None:
    frame_limit = 1_048_576 + 65_536
    native_echo.sendall(struct.pack("<I", frame_limit + 1))
    assert native_echo.recv(1) == b""


@pytest.mark.parametrize(
    "operation",
    [
        lambda _owner: OwnerIndex(1 << 57, 4096, 1, 1, _INCARNATION, _EXPIRY_NS),
        lambda owner: owner.session_ring(1 << 60),
        lambda owner: owner.session_ring(1 << 61),
    ],
    ids=(
        "index-file-offset-overflow",
        "ring-file-offset-overflow",
        "ring-byte-overflow",
    ),
)
def test_unrepresentable_mapping_sizes_fail_before_allocation(
    native_owner: OwnerIndex,
    operation: Callable[[OwnerIndex], object],
) -> None:
    with pytest.raises(OSError, match="invalid input parameter"):
        operation(native_owner)


@contextmanager
def _descriptor_budget(free_slots: NonNegativeInt) -> Generator[None]:
    limits = resource.getrlimit(resource.RLIMIT_NOFILE)
    probes = [os.open(os.devnull, os.O_RDONLY) for _ in range(free_slots)]
    soft_limit = probes[-1] + 1 if probes else 0
    for descriptor in probes:
        os.close(descriptor)
    try:
        resource.setrlimit(resource.RLIMIT_NOFILE, (soft_limit, limits[1]))
        yield
    finally:
        resource.setrlimit(resource.RLIMIT_NOFILE, limits)


def _descriptor_allocation_failure(
    operation: DescriptorOperation, temporary_parent: Path
) -> None:
    owner = OwnerIndex(8, 4096, 1, 1, _INCARNATION, _EXPIRY_NS)
    if operation == "echo":
        with (
            TemporaryDirectory(dir=temporary_parent) as directory,
            _descriptor_budget(1),
            pytest.raises(OSError, match="Too many open files"),
        ):
            owner.serve(str(Path(directory) / "echo.sock"))
        return
    operations: dict[DescriptorOperation, Callable[[], object]] = {
        "owner": lambda: OwnerIndex(8, 4096, 1, 1, _INCARNATION, _EXPIRY_NS),
        "ring": lambda: owner.session_ring(8),
        "descriptor": owner.reader_descriptor,
    }
    with _descriptor_budget(0), pytest.raises(OSError, match="Too many open files"):
        operations[operation]()


@pytest.fixture
def descriptor_failure_process(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[Callable[[DescriptorOperation], BaseProcess]]:
    processes: list[BaseProcess] = []

    def start(operation: DescriptorOperation) -> BaseProcess:
        process = multiprocessing.get_context("spawn").Process(
            target=_descriptor_allocation_failure,
            args=(operation, tmp_path_factory.getbasetemp()),
        )
        process.start()
        processes.append(process)
        return process

    yield start
    reclaim_workers(tuple(processes), monotonic() + 10, graceful=True)


@pytest.mark.parametrize(
    "operation",
    ["owner", "ring", "descriptor", "echo"],
    ids=("owner", "ring", "descriptor", "echo"),
)
def test_descriptor_exhaustion_is_reported(
    descriptor_failure_process: Callable[[DescriptorOperation], BaseProcess],
    operation: DescriptorOperation,
) -> None:
    process = descriptor_failure_process(operation)
    process.join(timeout=10)
    assert process.exitcode == 0
