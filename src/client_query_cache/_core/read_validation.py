from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from client_query_cache._shared_index import UnsafeScan

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
_SAFE_SCALAR_TYPES = (int, float, bool, bytes, bytearray, type(None))
_MAPPING_TYPES = (dict, Mapping)


def _contains_unsafe_construct(node: object, unsafe_keys: frozenset[str]) -> bool:
    node_type = type(node)
    if node_type in _SAFE_SCALAR_TYPES:
        return False
    if isinstance(node, _MAPPING_TYPES):
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


def _scan(unsafe_keys: frozenset[str]) -> UnsafeScan:
    return UnsafeScan(
        unsafe_keys,
        UNCACHEABLE_SYSTEM_VARIABLES,
        _UNCACHEABLE_VARIABLE_PREFIXES,
        Mapping,
        Sequence,
        _contains_unsafe_construct,
    )


_PIPELINE_SCAN = _scan(PIPELINE_UNSAFE_KEYS)
_FILTER_SCAN = _scan(FILTER_UNSAFE_KEYS)
_PROJECTION_SCAN = _scan(PROJECTION_UNSAFE_KEYS)


def is_pipeline_cacheable(pipeline: Sequence[Mapping[str, Any]]) -> bool:
    return not any(
        "$changeStream" in stage for stage in pipeline
    ) and not _PIPELINE_SCAN(pipeline)


def is_filter_cacheable(filter_query: Mapping[str, Any] | None) -> bool:
    if filter_query is None:
        return True
    return not _FILTER_SCAN(filter_query)


def is_projection_cacheable(
    projection: Mapping[str, Any] | Sequence[str] | None,
) -> bool:
    if projection is None:
        return True
    return not _PROJECTION_SCAN(projection)
