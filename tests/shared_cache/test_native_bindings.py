from __future__ import annotations

import multiprocessing
import os
import resource
import struct
import sys
from contextlib import ExitStack, contextmanager
from tempfile import TemporaryFile
from time import monotonic, monotonic_ns
from typing import TYPE_CHECKING, Literal

import pytest

from benchmarks.stream_cost.multiprocess_run import reclaim_workers
from client_query_cache import CacheCoreConfig
from client_query_cache._core.codec import encode_value
from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.keys import NamespaceId
from client_query_cache._shared_index import OwnerIndex, ReaderIndex, SharedOwnerCore
from client_query_cache._types import NonEmptyStr, NonNegativeInt, PositiveInt
from tests.epoch_helpers import current_epoch
from tests.shared_cache.index_helpers import assign_slot, shape_key

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterator
    from multiprocessing.process import BaseProcess
    from pathlib import Path

    from faker import Faker

    from client_query_cache._shared_index import SessionRing

type DescriptorOperation = Literal["owner", "ring", "descriptor"]

pytestmark = pytest.mark.unit

_INCARNATION = 41
_EXPIRY_NS = 60 * 10**9
_PROBE_TTL_SECONDS = 30.0
_USIZE_MAX = 2 * sys.maxsize + 1
_NAMESPACE = NamespaceId("native", "values")


@pytest.fixture
def native_owner() -> OwnerIndex:
    owner = OwnerIndex(8, 4096, 1, 1, _INCARNATION, _EXPIRY_NS)
    owner.set_progress(0, monotonic_ns())
    owner.enable_capture(enabled=True)
    return owner


@pytest.fixture
def shared_core(native_owner: OwnerIndex) -> Iterator[SharedOwnerCore]:
    core = SharedOwnerCore(
        CacheCoreConfig(max_namespaces=1),
        native_owner,
        [_NAMESPACE.database],
        1,
        _PROBE_TTL_SECONDS,
    )
    yield core
    core.close()


@pytest.fixture
def assigned_slot(
    shared_core: SharedOwnerCore,
) -> tuple[NonNegativeInt, NonNegativeInt]:
    slot = assign_slot(shared_core, _NAMESPACE)
    assert slot is not None
    return slot


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
def mapped_descriptor(tmp_path: Path) -> Iterator[Callable[[bytes], NonNegativeInt]]:
    with ExitStack() as resources:

        def create(contents: bytes) -> NonNegativeInt:
            temporary_file = resources.enter_context(TemporaryFile(dir=tmp_path))
            descriptor = temporary_file.fileno()
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


def test_rejects_an_out_of_range_progress_update(native_owner: OwnerIndex) -> None:
    with pytest.raises(ValueError, match="outside the index layout"):
        native_owner.set_progress(1, monotonic_ns())


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


def test_detached_reader_never_reads_or_enqueues(
    shared_core: SharedOwnerCore,
    assigned_slot: tuple[NonNegativeInt, NonNegativeInt],
    native_reader: ReaderIndex,
) -> None:
    epoch = current_epoch(shared_core, _NAMESPACE)
    assert native_reader.incarnation == _INCARNATION
    assert native_reader.admissions_enabled
    assert (native_reader.detached,) == (False,)
    assert native_reader.capture(*assigned_slot, epoch) is not None
    native_reader.detach()
    native_reader.detach()
    assert native_reader.detached
    assert native_reader.lookup(*assigned_slot, epoch, b"identity", b"shape") is None
    assert native_reader.capture(*assigned_slot, epoch) is None
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
def test_published_payloads_are_read_by_identity_and_withdrawn_by_a_write(
    *,
    shared_core: SharedOwnerCore,
    native_owner: OwnerIndex,
    native_reader: ReaderIndex,
    native_ring: SessionRing,
    assigned_slot: tuple[NonNegativeInt, NonNegativeInt],
    faker: Faker,
    identity_bytes: NonNegativeInt,
) -> None:
    identity = faker.binary(length=identity_bytes)
    shape = shape_key("shape")
    expected = encode_value({"value": faker.pystr(max_chars=32)})
    epoch = current_epoch(shared_core, _NAMESPACE)
    capture = shared_core.begin_identity_admission(_NAMESPACE, "identity")
    outcome = shared_core.admit_identity_published(
        capture, "shape", expected, identity, shape
    )
    assert outcome is AdmissionOutcome.ADMITTED
    assert native_owner.published() == 1
    assert native_reader.lookup(*assigned_slot, epoch, identity, shape) == expected
    shared_core.touch(native_ring)
    shared_core.record_write(_NAMESPACE, "identity")
    assert native_owner.published() == 0
    assert native_reader.lookup(*assigned_slot, epoch, identity, shape) is None


def test_damaged_admission_queue_reports_a_binding_error(
    native_ring: SessionRing,
    open_ring: Callable[[PositiveInt, NonNegativeInt], SessionRing],
) -> None:
    queue_start = os.fstat(open_ring(8, 0).descriptor()).st_size
    # Publish one word whose frame length is still zero, as in a damaged peer queue.
    os.pwrite(native_ring.descriptor(), struct.pack("<QQ", 0, 1), queue_start)
    with pytest.raises(ValueError, match="damaged admission queue"):
        native_ring.drain_admissions()


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
def _exhausted_descriptors() -> Generator[None]:
    limits = resource.getrlimit(resource.RLIMIT_NOFILE)
    try:
        resource.setrlimit(resource.RLIMIT_NOFILE, (0, limits[1]))
        yield
    finally:
        resource.setrlimit(resource.RLIMIT_NOFILE, limits)


def _descriptor_allocation_failure(operation: DescriptorOperation) -> None:
    owner = OwnerIndex(8, 4096, 1, 1, _INCARNATION, _EXPIRY_NS)
    operations: dict[DescriptorOperation, Callable[[], object]] = {
        "owner": lambda: OwnerIndex(8, 4096, 1, 1, _INCARNATION, _EXPIRY_NS),
        "ring": lambda: owner.session_ring(8),
        "descriptor": owner.reader_descriptor,
    }
    with _exhausted_descriptors(), pytest.raises(OSError, match="Too many open files"):
        operations[operation]()


@pytest.fixture
def descriptor_failure_process() -> Iterator[
    Callable[[DescriptorOperation], BaseProcess]
]:
    processes: list[BaseProcess] = []

    def start(operation: DescriptorOperation) -> BaseProcess:
        process = multiprocessing.get_context("spawn").Process(
            target=_descriptor_allocation_failure, args=(operation,)
        )
        process.start()
        processes.append(process)
        return process

    yield start
    reclaim_workers(tuple(processes), monotonic() + 10, graceful=True)


@pytest.mark.parametrize(
    "operation",
    ["owner", "ring", "descriptor"],
    ids=("owner", "ring", "descriptor"),
)
def test_descriptor_exhaustion_is_reported(
    descriptor_failure_process: Callable[[DescriptorOperation], BaseProcess],
    operation: DescriptorOperation,
) -> None:
    process = descriptor_failure_process(operation)
    process.join(timeout=10)
    assert process.exitcode == 0
