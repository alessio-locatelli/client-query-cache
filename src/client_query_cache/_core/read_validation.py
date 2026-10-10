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
        "$search",
        "$searchMeta",
        "$vectorSearch",
        "$listSearchIndexes",
        "$geoNear",
    }
)

FILTER_UNSAFE_KEYS = frozenset(
    {
        "$where",
        "$rand",
        "$sampleRate",
        "$function",
        "$accumulator",
        "$text",
        "$near",
        "$nearSphere",
    }
)

PROJECTION_UNSAFE_KEYS = frozenset({"$meta", "$rand", "$function"})

UNCACHEABLE_SYSTEM_VARIABLES = frozenset({"$$NOW", "$$CLUSTER_TIME", "$$USER_ROLES"})

_UNCACHEABLE_VARIABLE_PREFIXES = tuple(
    f"{variable}." for variable in UNCACHEABLE_SYSTEM_VARIABLES
)


def _contains_unsafe_construct(node: object, unsafe_keys: frozenset[str]) -> bool:
    if isinstance(node, Mapping):
        for key, value in node.items():
            if not isinstance(key, str) or key in unsafe_keys:
                return True
            if _contains_unsafe_construct(value, unsafe_keys):
                return True
        return False
    if isinstance(node, str):
        try:
            if node in UNCACHEABLE_SYSTEM_VARIABLES:
                return True
        except TypeError:
            return False
        return node.startswith(_UNCACHEABLE_VARIABLE_PREFIXES)
    if isinstance(node, Sequence) and not isinstance(node, (bytes, bytearray)):
        return any(_contains_unsafe_construct(item, unsafe_keys) for item in node)
    return False


def is_pipeline_cacheable(pipeline: Sequence[Mapping[str, Any]]) -> bool:
    return not any(
        "$changeStream" in stage for stage in pipeline
    ) and not _contains_unsafe_construct(pipeline, PIPELINE_UNSAFE_KEYS)


def is_filter_cacheable(filter_query: Mapping[str, Any] | None) -> bool:
    if filter_query is None:
        return True
    return not _contains_unsafe_construct(filter_query, FILTER_UNSAFE_KEYS)


def is_projection_cacheable(
    projection: Mapping[str, Any] | Sequence[str] | None,
) -> bool:
    if projection is None:
        return True
    return not _contains_unsafe_construct(projection, PROJECTION_UNSAFE_KEYS)
