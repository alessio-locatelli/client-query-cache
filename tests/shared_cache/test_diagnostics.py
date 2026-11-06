from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import pytest
from hypothesis import given
from hypothesis import strategies as st

from client_query_cache._core.snapshots import BypassReason
from client_query_cache._shared.adapters import LocalObservation
from client_query_cache._shared.diagnostics import SharedBypassReason

if TYPE_CHECKING:
    from faker import Faker

    from client_query_cache._types import NonNegativeInt

pytestmark = pytest.mark.unit

_SHARED_VALUES = {reason.value for reason in SharedBypassReason}
_UNREACHABLE_FROM_SHARED_READS = {BypassReason.ADMISSION_INVALIDATED.value}
_WRITERS = 4
_RECORDINGS_PER_WRITER = 500


def test_vocabulary_covers_every_reason_shared_reads_can_record() -> None:
    process_local = {reason.value for reason in BypassReason}
    assert process_local - _UNREACHABLE_FROM_SHARED_READS <= _SHARED_VALUES


@given(reasons=st.lists(st.one_of(st.sampled_from(sorted(_SHARED_VALUES)), st.text())))
def test_recorded_reasons_stay_bounded_and_conserve_totals(reasons: list[str]) -> None:
    observation = LocalObservation()
    for reason in reasons:
        observation.record_bypass(reason)
    snapshot = observation.snapshot()
    assert len(observation.bypasses) <= len(SharedBypassReason)
    assert [count.reason for count in snapshot.bypass_reasons] == list(
        SharedBypassReason
    )
    assert sum(count.count for count in snapshot.bypass_reasons) == len(reasons)
    assert snapshot.bypasses == len(reasons)


def test_unknown_reasons_count_as_unspecified(faker: Faker) -> None:
    unknown = faker.uuid4()
    observation = LocalObservation()
    observation.record_bypass(unknown)
    observation.record_bypass(SharedBypassReason.SESSION)
    totals = {
        count.reason: count.count for count in observation.snapshot().bypass_reasons
    }
    assert totals[SharedBypassReason.UNSPECIFIED] == 1
    assert totals[SharedBypassReason.SESSION] == 1


@pytest.mark.parametrize(
    ("oversized", "ordinary"),
    [
        pytest.param(0, 0, id="nothing-recorded"),
        pytest.param(2, 0, id="only-oversized"),
        pytest.param(0, 3, id="only-ordinary"),
        pytest.param(2, 3, id="both"),
    ],
)
def test_oversized_results_are_counted_apart_from_ordinary_bypasses(
    oversized: NonNegativeInt, ordinary: NonNegativeInt
) -> None:
    observation = LocalObservation()
    for _ in range(oversized):
        observation.record_oversized_bypass()
    for _ in range(ordinary):
        observation.record_bypass(BypassReason.SESSION)
    snapshot = observation.snapshot()
    assert snapshot.oversized_bypasses == oversized
    assert snapshot.bypasses == ordinary
    assert sum(count.count for count in snapshot.bypass_reasons) == ordinary


def test_concurrent_recording_never_breaks_reason_totals(faker: Faker) -> None:
    observation = LocalObservation()
    unknown_reasons = [faker.uuid4() for _ in range(_RECORDINGS_PER_WRITER)]

    def record_and_inspect(_writer: NonNegativeInt) -> list[int]:
        differences = []
        for reason in unknown_reasons:
            observation.record_bypass(reason)
            snapshot = observation.snapshot()
            differences.append(
                sum(count.count for count in snapshot.bypass_reasons)
                - snapshot.bypasses
            )
        return differences

    with ThreadPoolExecutor(_WRITERS) as pool:
        differences = [
            difference
            for writer_differences in pool.map(record_and_inspect, range(_WRITERS))
            for difference in writer_differences
        ]

    assert set(differences) == {0}
