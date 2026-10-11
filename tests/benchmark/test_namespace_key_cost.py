from __future__ import annotations

import gc
import json
import statistics
import tracemalloc
from time import process_time
from typing import TYPE_CHECKING

import pytest
from bson.codec_options import CodecOptions

from client_query_cache._core.canonical import canonicalize
from client_query_cache._core.codec import codec_fingerprint
from client_query_cache._core.find_one_reads import (
    find_one_read_shape,
    generic_find_one_discriminator,
)
from client_query_cache._core.order_sensitive_keys import (
    order_sensitive_discriminator_key,
)
from client_query_cache._types import BsonDict, NonNegativeFloat, NonNegativeInt

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.benchmark, pytest.mark.timeout(180)]
RETAINED_KEYS = 20_000
IN_VALUES = 48
REPETITIONS = 10
BUILDS_PER_REPETITION = 100


@pytest.fixture
def traced_read_shape() -> Iterator[object]:
    yield canonicalize(
        find_one_read_shape(None, None, None, codec_fingerprint(CodecOptions()))
    )
    tracemalloc.stop()


def code_filter(index: NonNegativeInt, *, states: bool) -> BsonDict:
    code = f"C{index:07d}"
    if not states:
        return {"code": code}
    return {
        "code": code,
        "state": {
            "$in": [f"state-{value:02d}-{index:07d}" for value in range(IN_VALUES)]
        },
    }


def find_one_discriminator(filter_query: BsonDict, read_shape: object) -> object:
    return canonicalize(
        generic_find_one_discriminator(
            canonicalize(order_sensitive_discriminator_key(filter_query)),
            read_shape,
            0,
        )
    )


def tuples(node: object, shared: object) -> NonNegativeInt:
    if node is shared or not isinstance(node, tuple):
        return 0
    return 1 + sum(tuples(item, shared) for item in node)


@pytest.mark.parametrize("states", [False, True], ids=["code", "code-and-states"])
def test_namespace_key_cost(traced_read_shape: object, *, states: bool) -> None:
    filters = [code_filter(index, states=states) for index in range(RETAINED_KEYS)]
    keys: list[object] = [None] * RETAINED_KEYS
    gc.collect()
    tracemalloc.start()
    before, _ = tracemalloc.get_traced_memory()
    for index, filter_query in enumerate(filters):
        keys[index] = find_one_discriminator(filter_query, traced_read_shape)
    retained, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    timings: list[NonNegativeFloat] = []
    for repetition in range(REPETITIONS):
        start = repetition * BUILDS_PER_REPETITION
        selected = filters[start : start + BUILDS_PER_REPETITION]
        started = process_time()
        for filter_query in selected:
            find_one_discriminator(filter_query, traced_read_shape)
        timings.append((process_time() - started) / BUILDS_PER_REPETITION)
    print(
        json.dumps(
            {
                "filter": "code-and-states" if states else "code",
                "tuples_per_key": tuples(keys[0], traced_read_shape),
                "bytes_per_key": round((retained - before) / RETAINED_KEYS),
                "cpu_us": round(statistics.median(timings) * 1e6, 1),
            }
        )
    )
