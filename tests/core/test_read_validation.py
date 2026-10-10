from __future__ import annotations

import pytest

from client_query_cache._core.read_validation import (
    is_filter_cacheable,
    is_pipeline_cacheable,
    is_projection_cacheable,
)
from client_query_cache._types import BsonDict

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "pipeline",
    [
        pytest.param([{"$match": {"a": 1}}], id="plain-match"),
        pytest.param([{"$project": {"a": 1}}, {"$limit": 5}], id="project-and-limit"),
        pytest.param([], id="empty-pipeline"),
        pytest.param(
            [{"$project": {"value": {"$literal": {"$changeStream": 1}}}}],
            id="change-stream-literal",
        ),
        pytest.param(
            [
                {
                    "$rankFusion": {
                        "input": {
                            "pipelines": {
                                "recent": [
                                    {"$match": {"a": 1}},
                                    {"$sort": {"createdAt": -1}},
                                ],
                                "popular": [{"$sort": {"views": -1}}],
                            }
                        }
                    }
                }
            ],
            id="rank-fusion-of-match-and-sort",
        ),
    ],
)
def test_safe_pipelines_are_cacheable(pipeline: list[BsonDict]) -> None:
    assert is_pipeline_cacheable(pipeline) is True


@pytest.mark.parametrize(
    "pipeline",
    [
        pytest.param([{"$lookup": {"from": "other"}}], id="lookup"),
        pytest.param([{"$changeStream": {}}], id="change-stream"),
        pytest.param([{"$unionWith": {"coll": "other"}}], id="union-with"),
        pytest.param([{"$graphLookup": {"from": "other"}}], id="graph-lookup"),
        pytest.param([{"$out": "other"}], id="out"),
        pytest.param([{"$merge": {"into": "other"}}], id="merge"),
        pytest.param([{"$sample": {"size": 1}}], id="sample"),
        pytest.param([{"$project": {"r": {"$function": {}}}}], id="function"),
        pytest.param(
            [{"$group": {"_id": None, "r": {"$accumulator": {}}}}], id="accumulator"
        ),
        pytest.param([{"$match": {"$expr": {"$rand": {}}}}], id="rand"),
        pytest.param([{"$match": {"$expr": {"$sampleRate": 0.5}}}], id="sample-rate"),
        pytest.param(
            [{"$match": {"$expr": {"$eq": ["$a", "$$NOW"]}}}], id="now-variable"
        ),
        pytest.param(
            [{"$match": {"$expr": {"$eq": ["$a", "$$CLUSTER_TIME"]}}}],
            id="cluster-time-variable",
        ),
        pytest.param(
            [{"$match": {"$expr": {"$eq": ["$a", "$$CLUSTER_TIME.t"]}}}],
            id="cluster-time-field-path",
        ),
        pytest.param(
            [{"$facet": {"nested": [{"$lookup": {"from": "other"}}]}}],
            id="nested-inside-facet",
        ),
        pytest.param([{"$collStats": {"count": {}}}], id="coll-stats"),
        pytest.param([{"$indexStats": {}}], id="index-stats"),
        pytest.param([{"$planCacheStats": {}}], id="plan-cache-stats"),
        pytest.param(
            [{"$project": {"score": {"$meta": "textScore"}}}], id="meta-projection"
        ),
        pytest.param(
            [{"$match": {"$text": {"$search": "coffee"}}}], id="text-search-match"
        ),
        pytest.param(
            [{"$search": {"text": {"query": "coffee", "path": "a"}}}], id="search"
        ),
        pytest.param(
            [{"$searchMeta": {"text": {"query": "coffee", "path": "a"}}}],
            id="search-meta",
        ),
        pytest.param(
            [
                {
                    "$vectorSearch": {
                        "index": "embedding",
                        "path": "embedding",
                        "queryVector": [0.5, 0.5],
                        "numCandidates": 1,
                        "limit": 1,
                    }
                }
            ],
            id="vector-search",
        ),
        pytest.param([{"$listSearchIndexes": {}}], id="list-search-indexes"),
        pytest.param(
            [
                {
                    "$rankFusion": {
                        "input": {
                            "pipelines": {
                                "searched": [
                                    {
                                        "$search": {
                                            "text": {"query": "coffee", "path": "a"}
                                        }
                                    }
                                ],
                                "sorted": [{"$sort": {"a": 1}}],
                            }
                        }
                    }
                }
            ],
            id="search-nested-inside-rank-fusion",
        ),
        pytest.param(
            [
                {
                    "$geoNear": {
                        "near": {"type": "Point", "coordinates": [0, 0]},
                        "distanceField": "distance",
                    }
                }
            ],
            id="geo-near",
        ),
        pytest.param(
            [{"$project": {"roles": "$$USER_ROLES"}}], id="user-roles-variable"
        ),
        pytest.param(
            [{"$project": {"roles": "$$USER_ROLES.role"}}],
            id="user-roles-field-path",
        ),
    ],
)
def test_unsafe_pipelines_are_not_cacheable(pipeline: list[BsonDict]) -> None:
    assert is_pipeline_cacheable(pipeline) is False


@pytest.mark.parametrize(
    "filter_query",
    [
        pytest.param(None, id="no-filter"),
        pytest.param({}, id="empty-filter"),
        pytest.param({"a": 1}, id="plain-equality"),
        pytest.param({"a": {"$gt": 1}}, id="range-operator"),
    ],
)
def test_safe_filters_are_cacheable(filter_query: BsonDict | None) -> None:
    assert is_filter_cacheable(filter_query) is True


@pytest.mark.parametrize(
    "filter_query",
    [
        pytest.param({"$where": "this.a > 1"}, id="where"),
        pytest.param({"$and": [{"$where": "true"}]}, id="nested-where"),
        pytest.param({"$expr": {"$rand": {}}}, id="expr-rand"),
        pytest.param({"$expr": {"$sampleRate": 0.5}}, id="expr-sample-rate"),
        pytest.param({"$expr": {"$eq": ["$a", "$$NOW"]}}, id="expr-now"),
        pytest.param(
            {"$expr": {"$eq": ["$a", "$$CLUSTER_TIME"]}}, id="expr-cluster-time"
        ),
        pytest.param(
            {"$expr": {"$eq": ["$a", "$$CLUSTER_TIME.t"]}},
            id="expr-cluster-time-field-path",
        ),
        pytest.param({"$expr": {"$function": {}}}, id="expr-function"),
        pytest.param({"$expr": {"$accumulator": {}}}, id="expr-accumulator"),
        pytest.param({"$text": {"$search": "coffee"}}, id="text-search"),
        pytest.param(
            {"$and": [{"$text": {"$search": "coffee"}}]}, id="nested-text-search"
        ),
        pytest.param(
            {"loc": {"$near": {"$geometry": {"type": "Point", "coordinates": [0, 0]}}}},
            id="near",
        ),
        pytest.param(
            {
                "loc": {
                    "$nearSphere": {
                        "$geometry": {"type": "Point", "coordinates": [0, 0]}
                    }
                }
            },
            id="near-sphere",
        ),
        pytest.param(
            {"$and": [{"loc": {"$near": [0, 0]}}, {"a": 1}]}, id="nested-near"
        ),
        pytest.param(
            {"$expr": {"$in": ["admin", "$$USER_ROLES.role"]}}, id="expr-user-roles"
        ),
    ],
)
def test_unsafe_filters_are_not_cacheable(filter_query: BsonDict) -> None:
    assert is_filter_cacheable(filter_query) is False


@pytest.mark.parametrize(
    "projection",
    [
        pytest.param(None, id="no-projection"),
        pytest.param({"a": 1}, id="plain-inclusion"),
        pytest.param({"a": 0}, id="plain-exclusion"),
        pytest.param(["a", "b"], id="field-name-list"),
        pytest.param({"a": 1, "b": {"$concat": ["$c", "$d"]}}, id="concat-of-fields"),
    ],
)
def test_safe_projections_are_cacheable(
    projection: BsonDict | list[str] | None,
) -> None:
    assert is_projection_cacheable(projection) is True


@pytest.mark.parametrize(
    "projection",
    [
        pytest.param({"score": {"$meta": "textScore"}}, id="meta"),
        pytest.param({"r": {"$rand": {}}}, id="rand"),
        pytest.param({"r": {"$function": {}}}, id="function"),
        pytest.param({"now": "$$NOW"}, id="now-variable"),
        pytest.param({"time": "$$CLUSTER_TIME"}, id="cluster-time-variable"),
        pytest.param({"time": "$$CLUSTER_TIME.t"}, id="cluster-time-field-path"),
        pytest.param({"roles": "$$USER_ROLES"}, id="user-roles-variable"),
    ],
)
def test_unsafe_projections_are_not_cacheable(projection: BsonDict) -> None:
    assert is_projection_cacheable(projection) is False
