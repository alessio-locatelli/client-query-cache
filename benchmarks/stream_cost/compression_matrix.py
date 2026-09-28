from __future__ import annotations

import enum
from dataclasses import dataclass

from benchmarks.stream_cost.client import WireCompressor
from benchmarks.stream_cost.errors import BenchmarkConfigurationError
from benchmarks.stream_cost.generators import (
    LARGE_DOCUMENT_PROFILE,
    SMALL_DOCUMENT_PROFILE,
    DocumentSizeProfile,
)
from benchmarks.stream_cost.workload import OperationCounts, WorkloadKind

MINIMUM_COMPRESSION_BLOCKS = 4

WIRE_COMPRESSION_MODES: tuple[WireCompressor, ...] = (
    WireCompressor.NONE,
    WireCompressor.SNAPPY,
    WireCompressor.ZLIB,
    WireCompressor.ZSTD,
)

_IDLE_DOCUMENT_COUNT = 20
_ACTIVE_DOCUMENT_COUNT = 100
_IDLE_WINDOW_DURATION_SECONDS = 5.0
_BALANCED_SAMPLING = OperationCounts(reads=50, writes=50)
_WRITE_DOMINANT_SAMPLING = OperationCounts(reads=10, writes=100)


class WirePath(enum.Enum):
    NO_STREAM = "no_stream"
    STREAM_WATCHING = "stream_watching"


@dataclass(frozen=True, slots=True)
class CompressionWindowSpec:
    kind: WorkloadKind
    data_size: DocumentSizeProfile
    document_count: int
    idle_duration_seconds: float | None
    sampling: OperationCounts
    seed: int

    def __post_init__(self) -> None:
        if self.document_count <= 0:
            message = "document_count must be positive"
            raise BenchmarkConfigurationError(message)
        if self.kind is WorkloadKind.IDLE:
            if self.idle_duration_seconds is None or self.idle_duration_seconds <= 0:
                message = "idle windows must declare a positive idle_duration_seconds"
                raise BenchmarkConfigurationError(message)
            if self.sampling.reads or self.sampling.writes:
                message = "idle windows must not sample reads or writes"
                raise BenchmarkConfigurationError(message)
        else:
            if self.idle_duration_seconds is not None:
                message = "only idle windows declare idle_duration_seconds"
                raise BenchmarkConfigurationError(message)
            if self.sampling.reads <= 0 and self.sampling.writes <= 0:
                message = "active windows must sample at least one read or write"
                raise BenchmarkConfigurationError(message)

    @property
    def name(self) -> str:
        if self.kind is WorkloadKind.IDLE:
            return "idle"
        return f"{self.kind.value}-{self.data_size.name}"


_IDLE_WINDOW = CompressionWindowSpec(
    kind=WorkloadKind.IDLE,
    data_size=SMALL_DOCUMENT_PROFILE,
    document_count=_IDLE_DOCUMENT_COUNT,
    idle_duration_seconds=_IDLE_WINDOW_DURATION_SECONDS,
    sampling=OperationCounts(reads=0, writes=0),
    seed=0,
)

_ACTIVE_WINDOW_PARAMETERS: tuple[
    tuple[WorkloadKind, DocumentSizeProfile, OperationCounts], ...
] = (
    (WorkloadKind.BALANCED, SMALL_DOCUMENT_PROFILE, _BALANCED_SAMPLING),
    (WorkloadKind.BALANCED, LARGE_DOCUMENT_PROFILE, _BALANCED_SAMPLING),
    (WorkloadKind.WRITE_DOMINANT, SMALL_DOCUMENT_PROFILE, _WRITE_DOMINANT_SAMPLING),
    (WorkloadKind.WRITE_DOMINANT, LARGE_DOCUMENT_PROFILE, _WRITE_DOMINANT_SAMPLING),
)

STANDARD_COMPRESSION_WINDOWS: tuple[CompressionWindowSpec, ...] = (
    _IDLE_WINDOW,
    *(
        CompressionWindowSpec(
            kind=kind,
            data_size=data_size,
            document_count=_ACTIVE_DOCUMENT_COUNT,
            idle_duration_seconds=None,
            sampling=sampling,
            seed=index + 1,
        )
        for index, (kind, data_size, sampling) in enumerate(_ACTIVE_WINDOW_PARAMETERS)
    ),
)


def _require_non_negative_block_index(block_index: int) -> None:
    if block_index < 0:
        message = "block_index must not be negative"
        raise BenchmarkConfigurationError(message)


def counterbalanced_mode_order(block_index: int) -> tuple[WireCompressor, ...]:
    _require_non_negative_block_index(block_index)
    rotation = block_index % len(WIRE_COMPRESSION_MODES)
    return WIRE_COMPRESSION_MODES[rotation:] + WIRE_COMPRESSION_MODES[:rotation]


def counterbalanced_path_order(block_index: int) -> tuple[WirePath, WirePath]:
    _require_non_negative_block_index(block_index)
    if block_index % 2 == 0:
        return (WirePath.NO_STREAM, WirePath.STREAM_WATCHING)
    return (WirePath.STREAM_WATCHING, WirePath.NO_STREAM)


def require_minimum_compression_blocks(block_count: int) -> None:
    if block_count < MINIMUM_COMPRESSION_BLOCKS:
        message = (
            f"block_count ({block_count}) must be at least "
            f"{MINIMUM_COMPRESSION_BLOCKS} repeated, counterbalanced blocks"
        )
        raise BenchmarkConfigurationError(message)
