"""Attribute live allocations and allocator retention in the registered builders."""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from client_query_cache._types import BsonDict, PositiveInt
from research.collection_adapter.live_error import fixture
from research.process_memory import measure

if TYPE_CHECKING:
    import memray

    from client_query_cache import CacheManager
    from client_query_cache.asynchronous import CacheManager as AsyncCacheManager


def acquire(
    api: Literal["sync", "async"],
    scenario: Literal["small-entries", "large-keys"],
    backend: Literal["reference", "native"],
    entries: PositiveInt,
    trace: Path | None,
) -> None:
    original_sample = measure.sample
    tracker: memray.Tracker | None = None
    libc = ctypes.CDLL(None)

    def checkpoint(
        phase: str,
        manager: CacheManager[BsonDict] | AsyncCacheManager[BsonDict] | None,
        **extra: object,
    ) -> None:
        nonlocal tracker
        original_sample(phase, manager, attribution_entries=entries, **extra)
        print(f"ALLOCATOR PHASE {phase}", file=sys.stderr, flush=True)
        sys._debugmallocstats()  # noqa: SLF001 - Inspect CPython pool/arena retention alongside process memory.
        libc.malloc_stats()
        if backend == "native" and manager is not None:
            ownership = manager.cache_core._ownership()  # type: ignore[attr-defined]  # noqa: SLF001 - Inspect the feature-built owner instead of treating retained RSS as live entries.
            print(
                json.dumps({"phase": phase, "ownership": ownership}),
                flush=True,
            )
        if phase == "baseline" and trace is not None:
            import memray  # noqa: PLC0415 - The optional profiler is needed only for allocation attribution.

            tracker = memray.Tracker(
                str(trace), native_traces=True, trace_python_allocators=True
            )
            tracker.__enter__()
        elif phase == "close" and tracker is not None:
            tracker.__exit__(None, None, None)
            tracker = None

    measure.COLD_CODES = entries
    if entries == 5000:
        measure.CODE_DOCUMENTS = entries
    measure.sample = checkpoint
    try:
        with fixture() as control:
            measure.seed(control)
            address = control.address
            assert address is not None
            uri = f"mongodb://{address[0]}:{address[1]}/?directConnection=true"
            asyncio.run(measure.child(uri, scenario, api, "cached", backend))
    finally:
        measure.sample = original_sample
        if tracker is not None:
            tracker.__exit__(None, None, None)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", choices=("sync", "async"), required=True)
    parser.add_argument(
        "--scenario", choices=("small-entries", "large-keys"), required=True
    )
    parser.add_argument("--backend", choices=("reference", "native"), required=True)
    parser.add_argument("--entries", type=int, choices=(5000, 64000), default=5000)
    parser.add_argument("--trace", type=Path)
    arguments = parser.parse_args()
    if arguments.trace is not None:
        arguments.trace.parent.mkdir(parents=True, exist_ok=True)
    acquire(
        arguments.api,
        arguments.scenario,
        arguments.backend,
        arguments.entries,
        arguments.trace,
    )


if __name__ == "__main__":
    main()
