from __future__ import annotations

from dataclasses import dataclass

from client_query_cache._types import PositiveInt


@dataclass(frozen=True, slots=True)
class SharedIndexLimits:
    slots: PositiveInt
    arena_bytes: PositiveInt
    namespaces: PositiveInt
    ring_tokens: PositiveInt
    local_miss_admission: bool = False
    native_admission_queue: bool = False

    def __post_init__(self) -> None:
        if self.native_admission_queue and not self.local_miss_admission:
            raise ValueError("native admission queues require local miss capture")
