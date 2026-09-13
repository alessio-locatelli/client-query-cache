from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

PIPELINE_UNSAFE_KEYS = frozenset(
    {
        "$lookup",
        "$unionWith",
        "$graphLookup",
        "$out",
        "$merge",
        "$sample",
        "$function",
        "$accumulator",
        "$rand",
        "$sampleRate",
        "$collStats",
        "$indexStats",
        "$planCacheStats",
    }
)

PIPELINE_BLOCKING_KEYS = frozenset({"$changeStream"})

FILTER_UNSAFE_KEYS = frozenset(
    {"$where", "$rand", "$sampleRate", "$function", "$accumulator"}
)

NONDETERMINISTIC_SYSTEM_VARIABLES = frozenset({"$$NOW", "$$CLUSTER_TIME"})

_NO_UNSAFE_VARIABLES: frozenset[str] = frozenset()


def _contains_unsafe_construct(
    node: object,
    unsafe_keys: frozenset[str],
    unsafe_variables: frozenset[str] = _NO_UNSAFE_VARIABLES,
) -> bool:
    if isinstance(node, Mapping):
        for key, value in node.items():
            if key in unsafe_keys:
                return True
            if _contains_unsafe_construct(value, unsafe_keys, unsafe_variables):
                return True
        return False
    if isinstance(node, str):
        try:
            return node in unsafe_variables
        except TypeError:
            return False
    if isinstance(node, Sequence) and not isinstance(node, (bytes, bytearray)):
        return any(
            _contains_unsafe_construct(item, unsafe_keys, unsafe_variables)
            for item in node
        )
    return False


def is_pipeline_cacheable(pipeline: Sequence[Mapping[str, Any]]) -> bool:
    return not _contains_unsafe_construct(
        pipeline, PIPELINE_UNSAFE_KEYS, NONDETERMINISTIC_SYSTEM_VARIABLES
    )


def pipeline_blocks_full_materialization(pipeline: Sequence[Mapping[str, Any]]) -> bool:
    return any(not PIPELINE_BLOCKING_KEYS.isdisjoint(stage) for stage in pipeline)


def is_filter_cacheable(filter_query: Mapping[str, Any] | None) -> bool:
    if filter_query is None:
        return True
    return not _contains_unsafe_construct(
        filter_query, FILTER_UNSAFE_KEYS, NONDETERMINISTIC_SYSTEM_VARIABLES
    )
