"""Attribute retained Python allocations separately from uninstrumented acquisition."""

from __future__ import annotations

import argparse
import asyncio
import json
import tracemalloc
from pathlib import Path
from typing import Literal

from research.collection_adapter.live_error import fixture
from research.process_memory import measure

_PROFILE_ENTRIES = 5_000
type Phase = Literal["baseline", "cold", "warm", "evict", "close", "trimmed"]


def acquire(
    api: Literal["sync", "async"],
    scenario: Literal["small-entries", "large-keys"],
    output: Path,
    backend: Literal["reference", "native"] = "reference",
) -> None:
    output.mkdir(parents=True, exist_ok=True)
    original_sample = measure.sample

    def checkpoint(phase: Phase, manager: object, **extra: object) -> None:
        original_sample(
            phase,
            manager,
            attribution_entries=_PROFILE_ENTRIES,
            attribution_eviction_reads=0,
            **extra,
        )
        if phase == "baseline":
            tracemalloc.start(25)
        snapshot = tracemalloc.take_snapshot()
        snapshot.dump(str(output / f"{phase}.trace"))
        current, peak = tracemalloc.get_traced_memory()
        print(
            json.dumps(
                {
                    "allocation_phase": "evict-noop" if phase == "evict" else phase,
                    "traced_current": current,
                    "traced_peak": peak,
                }
            ),
            flush=True,
        )
        tracemalloc.reset_peak()

    # Keep the existing document/filter and phase builders, bounding attribution
    # rather than tracing the much larger acceptance workload.
    measure.COLD_CODES = _PROFILE_ENTRIES
    measure.CODE_DOCUMENTS = _PROFILE_ENTRIES
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
        tracemalloc.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", choices=("sync", "async"), required=True)
    parser.add_argument(
        "--scenario", choices=("small-entries", "large-keys"), required=True
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--backend", choices=("reference", "native"), default="reference"
    )
    arguments = parser.parse_args()
    acquire(arguments.api, arguments.scenario, arguments.output, arguments.backend)


if __name__ == "__main__":
    main()
