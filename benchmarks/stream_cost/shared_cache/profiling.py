from __future__ import annotations

import cProfile
import os
import pstats
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from client_query_cache._types import JsonDict

if TYPE_CHECKING:
    from collections.abc import Generator

PROFILE_DIRECTORY = "SHARED_CACHE_PROFILE_DIRECTORY"
_TOP_FUNCTIONS = 25


class WindowProfiler:
    __slots__ = ("_profiler",)

    def __init__(self) -> None:
        self._profiler: cProfile.Profile | None = None

    def start(self) -> None:
        self._profiler = cProfile.Profile()
        self._profiler.enable()

    def stop(self, name: str) -> None:
        profiler = self._profiler
        assert profiler is not None
        profiler.disable()
        profiler.dump_stats(
            Path(os.environ[PROFILE_DIRECTORY]) / f"{name}-{os.getpid()}.prof"
        )
        self._profiler = None


def enabled() -> bool:
    return PROFILE_DIRECTORY in os.environ


@contextmanager
def profiling(name: str) -> Generator[None]:
    try:
        directory = os.environ[PROFILE_DIRECTORY]
    except KeyError:
        yield
        return
    profiler = cProfile.Profile()
    profiler.enable()
    try:
        yield
    finally:
        profiler.disable()
        profiler.dump_stats(Path(directory) / f"{name}-{os.getpid()}.prof")


def summarize(path: Path) -> JsonDict:
    statistics = pstats.Stats(str(path))
    rows = sorted(
        statistics.stats.items(),  # type: ignore[attr-defined]
        key=lambda item: item[1][2],
        reverse=True,
    )[:_TOP_FUNCTIONS]
    return {
        "total_seconds": statistics.total_tt,  # type: ignore[attr-defined]
        "functions": [
            {
                "function": f"{Path(filename).name}:{line}:{function}",
                "calls": calls,
                "own_seconds": own,
                "cumulative_seconds": cumulative,
            }
            for (filename, line, function), (_, calls, own, cumulative, _) in rows
        ],
    }
