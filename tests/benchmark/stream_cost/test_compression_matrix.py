from __future__ import annotations

import pytest

from benchmarks.stream_cost.compression_matrix import (
    MINIMUM_COMPRESSION_BLOCKS,
    STANDARD_COMPRESSION_WINDOWS,
    WARMUP_READ_REPEATS,
    WIRE_COMPRESSION_MODES,
    CompressionWindowSpec,
    WirePath,
    counterbalanced_mode_order,
    counterbalanced_path_order,
    require_minimum_compression_blocks,
)
from benchmarks.stream_cost.errors import BenchmarkConfigurationError
from benchmarks.stream_cost.generators import SMALL_DOCUMENT_PROFILE
from benchmarks.stream_cost.workload import OperationCounts, WorkloadKind
from client_query_cache._types import NonNegativeInt

pytestmark = pytest.mark.unit

_WARMUP = OperationCounts(reads=WARMUP_READ_REPEATS, writes=0)


def test_standard_compression_windows_covers_every_registered_combination() -> None:
    names = {window.name for window in STANDARD_COMPRESSION_WINDOWS}
    assert names == {
        "idle",
        "balanced-small",
        "balanced-large",
        "write_dominant-small",
        "write_dominant-large",
    }


def test_standard_compression_windows_are_uniquely_named() -> None:
    names = [window.name for window in STANDARD_COMPRESSION_WINDOWS]
    assert len(names) == len(set(names))


def test_idle_window_has_no_sampled_operations() -> None:
    (idle_window,) = (
        window
        for window in STANDARD_COMPRESSION_WINDOWS
        if window.kind is WorkloadKind.IDLE
    )
    assert idle_window.sampling == OperationCounts(reads=0, writes=0)
    assert idle_window.duration_seconds > 0


_ACTIVE_WINDOWS = [
    window
    for window in STANDARD_COMPRESSION_WINDOWS
    if window.kind != WorkloadKind.IDLE
]


@pytest.mark.parametrize("window", _ACTIVE_WINDOWS, ids=lambda window: window.name)
def test_active_windows_sample_at_least_one_operation(
    window: CompressionWindowSpec,
) -> None:
    assert window.sampling.reads or window.sampling.writes
    assert window.duration_seconds > 0


@pytest.mark.parametrize(
    ("kind", "sampling", "match"),
    [
        pytest.param(
            WorkloadKind.IDLE,
            OperationCounts(reads=1, writes=0),
            "must not sample",
            id="idle_with_sampling",
        ),
        pytest.param(
            WorkloadKind.BALANCED,
            OperationCounts(reads=0, writes=0),
            "at least one read or write",
            id="active_without_sampling",
        ),
    ],
)
def test_compression_window_spec_rejects_inconsistent_sampling(
    kind: WorkloadKind,
    sampling: OperationCounts,
    match: str,
) -> None:
    with pytest.raises(BenchmarkConfigurationError, match=match):
        CompressionWindowSpec(
            kind=kind,
            data_size=SMALL_DOCUMENT_PROFILE,
            document_count=10,
            duration_seconds=5.0,
            warmup=_WARMUP,
            sampling=sampling,
            seed=0,
        )


@pytest.mark.parametrize(
    ("field_name", "value", "match"),
    [
        pytest.param("document_count", 0, "document_count", id="zero_document_count"),
        pytest.param("duration_seconds", 0.0, "duration_seconds", id="zero_duration"),
        pytest.param(
            "duration_seconds", float("nan"), "duration_seconds", id="nan_duration"
        ),
        pytest.param(
            "warmup",
            OperationCounts(reads=1, writes=0),
            "warmup.reads",
            id="insufficient_warmup_reads",
        ),
    ],
)
def test_compression_window_spec_rejects_invalid_fields(
    field_name: str, value: object, match: str
) -> None:
    defaults: dict[str, object] = {
        "kind": WorkloadKind.IDLE,
        "data_size": SMALL_DOCUMENT_PROFILE,
        "document_count": 10,
        "duration_seconds": 5.0,
        "warmup": _WARMUP,
        "sampling": OperationCounts(reads=0, writes=0),
        "seed": 0,
    }
    defaults[field_name] = value
    with pytest.raises(BenchmarkConfigurationError, match=match):
        CompressionWindowSpec(**defaults)  # type: ignore[arg-type]


@pytest.mark.parametrize("block_index", range(8))
def test_counterbalanced_mode_order_is_a_rotation_covering_every_mode(
    block_index: NonNegativeInt,
) -> None:
    order = counterbalanced_mode_order(block_index)
    assert set(order) == set(WIRE_COMPRESSION_MODES)
    assert len(order) == len(WIRE_COMPRESSION_MODES)


def test_counterbalanced_mode_order_rotates_across_blocks() -> None:
    orders = {counterbalanced_mode_order(index) for index in range(4)}
    assert len(orders) == 4


def test_counterbalanced_mode_order_rejects_a_negative_block_index() -> None:
    with pytest.raises(BenchmarkConfigurationError, match="block_index"):
        counterbalanced_mode_order(-1)


@pytest.mark.parametrize(
    ("block_index", "expected"),
    [
        (0, (WirePath.NO_STREAM, WirePath.STREAM_WATCHING)),
        (1, (WirePath.STREAM_WATCHING, WirePath.NO_STREAM)),
        (2, (WirePath.NO_STREAM, WirePath.STREAM_WATCHING)),
        (3, (WirePath.STREAM_WATCHING, WirePath.NO_STREAM)),
    ],
)
def test_counterbalanced_path_order_alternates_across_blocks(
    block_index: NonNegativeInt, expected: tuple[WirePath, WirePath]
) -> None:
    assert counterbalanced_path_order(block_index) == expected


def test_counterbalanced_path_order_rejects_a_negative_block_index() -> None:
    with pytest.raises(BenchmarkConfigurationError, match="block_index"):
        counterbalanced_path_order(-1)


def test_require_minimum_compression_blocks_accepts_the_minimum() -> None:
    require_minimum_compression_blocks(MINIMUM_COMPRESSION_BLOCKS)


def test_require_minimum_compression_blocks_rejects_fewer_blocks() -> None:
    with pytest.raises(BenchmarkConfigurationError, match="block_count"):
        require_minimum_compression_blocks(MINIMUM_COMPRESSION_BLOCKS - 1)
