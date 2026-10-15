from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    invariant,
    rule,
    run_state_machine_as_test,
)

from client_query_cache._shared.shared_index import SharedIndexLimits
from client_query_cache._shared_index import OwnerIndex, ReaderIndex, SessionRing
from client_query_cache._types import NonNegativeInt, PositiveInt

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

_QUEUE_BYTES = 4_096
_THREADS = 8
_FRAMES = 100


@dataclass(slots=True)
class Queue:
    owner: OwnerIndex
    ring: SessionRing
    reader: ReaderIndex


def _queue(bytes_capacity: PositiveInt) -> Queue:
    owner = OwnerIndex(4, 4_096, 1, 1, 1, 10**9)
    ring = owner.session_ring(4, bytes_capacity)
    descriptor = owner.reader_descriptor()
    try:
        reader = ReaderIndex(descriptor, ring.descriptor())
    finally:
        os.close(descriptor)
    return Queue(owner, ring, reader)


@pytest.fixture
def queue() -> Iterator[Queue]:
    queued = _queue(_QUEUE_BYTES)
    yield queued
    queued.ring.close_descriptor()


@pytest.fixture
def producers() -> Iterator[ThreadPoolExecutor]:
    with ThreadPoolExecutor(max_workers=_THREADS) as executor:
        yield executor


def test_native_queues_require_local_capture() -> None:
    with pytest.raises(ValueError, match="require local miss capture"):
        SharedIndexLimits(4, 4_096, 1, 4, native_admission_queue=True)


def test_detached_readers_cannot_post_admissions(queue: Queue) -> None:
    assert queue.reader.enqueue_admission(b"before detachment")
    queue.reader.detach()
    assert not queue.reader.enqueue_admission(b"after detachment")
    assert queue.ring.drain_admissions() == [b"before detachment"]


@pytest.mark.parametrize("limit", [0, 1, 3], ids=("none", "one", "all"))
def test_bounded_drains_preserve_remaining_records(
    queue: Queue, limit: NonNegativeInt
) -> None:
    frames = [b"first", b"second", b"third"]
    assert all(queue.reader.enqueue_admission(frame) for frame in frames)
    assert queue.ring.drain_admissions(limit) == frames[:limit]
    assert queue.ring.drain_admissions() == frames[limit:]


def test_concurrent_producers_post_complete_records(
    queue: Queue, producers: ThreadPoolExecutor
) -> None:
    frames = [str(sequence).encode() for sequence in range(_FRAMES)]
    assert all(producers.map(queue.reader.enqueue_admission, frames))
    assert sorted(queue.ring.drain_admissions()) == sorted(frames)


class _AdmissionQueueMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.queue = _queue(128)
        self.accepted: list[bytes] = []

    def teardown(self) -> None:
        self.queue.ring.close_descriptor()

    @rule(frame=st.binary(min_size=1, max_size=256))
    def post(self, frame: bytes) -> None:
        if self.queue.reader.enqueue_admission(frame):
            self.accepted.append(frame)

    @rule()
    def drain(self) -> None:
        assert self.queue.ring.drain_admissions() == self.accepted
        self.accepted.clear()

    @invariant()
    def recency_touches_remain_separate(self) -> None:
        assert self.queue.ring.drain() == []


def test_admission_queue_operation_order() -> None:
    # Hypothesis does not annotate its state-machine runner.
    run_state_machine_as_test(  # type: ignore[no-untyped-call]
        _AdmissionQueueMachine, settings=settings(max_examples=60)
    )
