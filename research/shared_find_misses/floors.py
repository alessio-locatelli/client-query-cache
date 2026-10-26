# ruff: noqa: PLC2701 - Exercise installed native/internal paths without a MongoDB collector.
"""Measure native find lookup and family-filter maintenance."""

from __future__ import annotations

import argparse
import json
import os
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING

from bson.codec_options import CodecOptions

from client_query_cache._core.canonical import canonicalize
from client_query_cache._core.codec import codec_fingerprint
from client_query_cache._core.find_reads import find_read_shape
from client_query_cache._shared.wire import encode_key
from client_query_cache._shared_index import OwnerIndex, Payload, ReaderIndex
from client_query_cache._types import NonNegativeFloat, PositiveInt

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

_READS = 10_000
_MUTATIONS = 100
_PAYLOAD = b"x" * 4096


@contextmanager
def _mapping() -> Generator[tuple[OwnerIndex, ReaderIndex]]:
    owner = OwnerIndex(4096, 8 * 1024 * 1024, 1, 1, 1, 10**15)
    owner.set_available(0, available=True)
    owner.set_progress(0, time.monotonic_ns())
    owner.enable_capture(enabled=True)
    ring = owner.session_ring(65536)
    descriptor = owner.reader_descriptor()
    try:
        reader = ReaderIndex(descriptor, ring.descriptor())
        yield owner, reader
    finally:
        os.close(descriptor)
        ring.close_descriptor()


def _cpu_per_call(
    operation: Callable[[], object], calls: PositiveInt
) -> NonNegativeFloat:
    started = time.process_time_ns()
    for _ in range(calls):
        operation()
    return (time.process_time_ns() - started) / calls


def _batch(variants: PositiveInt, *, candidate: bool) -> dict[str, object]:
    family = canonicalize(
        find_read_shape(
            {"group": 1},
            None,
            {"ordinal": 1},
            0,
            1,
            collation=None,
            codec=codec_fingerprint(CodecOptions()),
        ).family
    )
    encoded_family = encode_key(family)
    limits = tuple(range(2, variants * 2 + 1, 2))
    shapes = {limit: encode_key(canonicalize((family, limit))) for limit in limits}
    blocks: list[Payload] = []
    with _mapping() as (owner, reader):

        def publish() -> None:
            for limit in limits:
                payload = owner.store(_PAYLOAD)
                assert payload is not None
                if candidate:
                    token = owner.publish_find(0, 0, 0, encoded_family, limit, payload)
                else:
                    token = owner.publish(0, 0, 0, b"", shapes[limit], payload)
                assert token is not None
                blocks.append(payload)

        def release() -> None:
            for payload in blocks:
                owner.release(payload)
            blocks.clear()

        def mutate() -> None:
            publish()
            release()

        publish()
        exact: Callable[[], object] = (
            (lambda: reader.lookup_find(0, 0, 0, encoded_family, limits[-1]))
            if candidate
            else (lambda: reader.lookup(0, 0, 0, b"", shapes[limits[-1]]))
        )
        assert exact() == _PAYLOAD
        observations: dict[str, object] = {
            "variants": variants,
            "exact_cpu_ns": _cpu_per_call(exact, _READS),
        }
        if candidate:

            def compatible() -> object:
                return reader.lookup_find(0, 0, 0, encoded_family, 1)

            assert compatible() is None
            observations["compatible_fallback_cpu_ns"] = _cpu_per_call(
                compatible, _READS
            )
            absent_family = encode_key("unpublished family")

            def absent() -> object:
                return reader.lookup_find(0, 0, 0, absent_family, 1)

            assert isinstance(absent(), tuple)
            observations["absent_capture_cpu_ns"] = _cpu_per_call(absent, _READS)
        release()
        observations["publish_remove_cpu_ns_per_entry"] = (
            _cpu_per_call(mutate, _MUTATIONS) / variants
        )
        assert owner.published() == 0
    return observations


def _saturation(families: PositiveInt) -> dict[str, object]:
    encoded_families = tuple(
        encode_key(("family", ordinal)) for ordinal in range(families)
    )
    blocks: list[Payload] = []
    with _mapping() as (owner, reader):
        for family in encoded_families:
            payload = owner.store(b"x")
            assert payload is not None
            assert owner.publish_find(0, 0, 0, family, 8, payload) is not None
            blocks.append(payload)
        for family in encoded_families:
            assert reader.lookup_find(0, 0, 0, family, 8) == b"x"
            assert reader.lookup_find(0, 0, 0, family, 4) is None
        false_positives = 0
        probes = 4096
        for ordinal in range(probes):
            selection = reader.lookup_find(0, 0, 0, encode_key(("absent", ordinal)), 4)
            if selection is None:
                false_positives += 1
            else:
                assert isinstance(selection, tuple)
        for payload in blocks:
            owner.release(payload)
        assert owner.published() == 0
        for family in encoded_families:
            assert isinstance(reader.lookup_find(0, 0, 0, family, 4), tuple)
    return {"families": families, "probes": probes, "false_positives": false_positives}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", action="store_true")
    parser.add_argument("--saturation", action="store_true")
    parser.add_argument("--repetitions", type=int, default=5)
    arguments = parser.parse_args()
    if arguments.repetitions <= 0:
        parser.error("repetitions must be positive")
    if arguments.saturation:
        if not arguments.candidate:
            parser.error("--saturation requires --candidate")
        print(
            json.dumps([_saturation(count) for count in (1, 128, 512, 2048)], indent=2)
        )
        return
    print(
        json.dumps(
            {
                "candidate": arguments.candidate,
                "read_calls": _READS,
                "mutation_cycles": _MUTATIONS,
                "batches": [
                    {
                        "repetition": repetition,
                        **_batch(variants, candidate=arguments.candidate),
                    }
                    for repetition in range(arguments.repetitions)
                    for variants in (1, 8, 64)
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
