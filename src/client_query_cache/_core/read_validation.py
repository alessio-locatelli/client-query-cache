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
        "$meta",
        "$text",
    }
)

PIPELINE_BLOCKING_KEYS = frozenset({"$changeStream"})

FILTER_UNSAFE_KEYS = frozenset(
    {"$where", "$rand", "$sampleRate", "$function", "$accumulator", "$text"}
)

PROJECTION_UNSAFE_KEYS = frozenset({"$meta"})

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
            if node in unsafe_variables:
                return True
        except TypeError:
            return False
        return any(node.startswith(f"{variable}.") for variable in unsafe_variables)
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


def is_projection_cacheable(
    projection: Mapping[str, Any] | Sequence[str] | None,
) -> bool:
    if projection is None:
        return True
    return not _contains_unsafe_construct(projection, PROJECTION_UNSAFE_KEYS)
