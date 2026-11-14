# ruff: noqa: PLC2701 - Measure installed native/internal encoders without MongoDB.
"""Measure paired shared cold-find key preparation in the installed release."""

from __future__ import annotations

import argparse
import json
import time
from typing import TYPE_CHECKING

from bson.codec_options import CodecOptions

from client_query_cache._core.canonical import canonicalize
from client_query_cache._core.codec import codec_fingerprint
from client_query_cache._core.find_reads import find_read_shape
from client_query_cache._shared.wire import KeyCache, encode_key
from client_query_cache._types import NonNegativeFloat, PositiveInt

if TYPE_CHECKING:
    from client_query_cache._core.canonical import Canonical


def measure(samples: PositiveInt) -> NonNegativeFloat:
    codec = codec_fingerprint(CodecOptions())
    families: tuple[Canonical, ...] = tuple(
        canonicalize(
            find_read_shape(
                {"group": group},
                None,
                [("ordinal", 1)],
                0,
                16,
                collation=None,
                codec=codec,
            ).family
        )
        for group in range(samples)
    )
    cache = KeyCache(8192)
    for family in (families[0], families[-1]):
        assert cache.find(family, 16) == (
            encode_key(family),
            encode_key(canonicalize((family, 16))),
        )
    cache = KeyCache(8192)
    started = time.process_time_ns()
    for family in families:
        cache.find(family, 16)
    return (time.process_time_ns() - started) / samples


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=10_000)
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be positive")
    print(
        json.dumps(
            {
                "samples": args.samples,
                "cpu_ns_per_query": measure(args.samples),
            }
        )
    )


if __name__ == "__main__":
    main()
