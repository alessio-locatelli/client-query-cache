from __future__ import annotations

from client_query_cache._core.selective_invalidation import (
    MAX_PROOF_BYTES,
    MAX_PROOF_PATHS,
    CollectionPolicies,
)
from client_query_cache._types import BsonDict


def _partition(field: str) -> BsonDict:
    scalar = {"$getField": {"field": {"$literal": field}, "input": "$fullDocument"}}
    return {
        "$let": {
            "vars": {"scalar": scalar},
            "in": {
                "$cond": [
                    {
                        "$cond": [
                            {"$eq": [{"$type": "$$scalar"}, "string"]},
                            {"$lte": [{"$strLenBytes": "$$scalar"}, MAX_PROOF_BYTES]},
                            {
                                "$in": [
                                    {"$type": "$$scalar"},
                                    ["int", "long", "bool", "objectId"],
                                ]
                            },
                        ]
                    },
                    {"known": True, "value": "$$scalar"},
                    {"known": False},
                ]
            },
        }
    }


def _changes() -> BsonDict:
    valid_name = {
        "$and": [
            {"$lte": [{"$strLenBytes": "$$name"}, MAX_PROOF_BYTES]},
            {
                "$not": [
                    {
                        "$regexMatch": {
                            "input": "$$name",
                            "regex": r"(^|\.)[0-9]+(\.|$)|(^\.|\.$|\.\.)|(^|\.)\$|\x00",
                        }
                    }
                ]
            },
        ]
    }
    names = {
        "$concatArrays": [
            {
                "$map": {
                    "input": {"$objectToArray": "$updateDescription.updatedFields"},
                    "as": "field",
                    "in": "$$field.k",
                }
            },
            "$updateDescription.removedFields",
            {
                "$map": {
                    "input": "$updateDescription.truncatedArrays",
                    "as": "field",
                    "in": "$$field.field",
                }
            },
        ]
    }
    bounded_names = {
        "$cond": [
            {
                "$allElementsTrue": {
                    "$map": {
                        "input": "$$names",
                        "as": "name",
                        "in": valid_name,
                    }
                }
            },
            {"known": True, "names": "$$names"},
            {"known": False},
        ]
    }
    bounded = {
        "$let": {
            "vars": {"names": names},
            "in": {
                "$cond": [
                    {"$lte": [{"$size": "$$names"}, MAX_PROOF_PATHS]},
                    bounded_names,
                    {"known": False},
                ]
            },
        }
    }
    return {
        "$cond": [
            {
                "$and": [
                    {"$eq": [{"$type": "$updateDescription.updatedFields"}, "object"]},
                    {"$isArray": "$updateDescription.removedFields"},
                    {"$isArray": "$updateDescription.truncatedArrays"},
                    {
                        "$eq": [
                            {"$ifNull": ["$updateDescription.disambiguatedPaths", {}]},
                            {},
                        ]
                    },
                ]
            },
            bounded,
            {"known": False},
        ]
    }


def selective_projection(policies: CollectionPolicies) -> BsonDict:
    partitions = []
    updates = []
    for collection, policy in policies.items():
        if policy.insert_partition_field is not None:
            partitions.append(
                {
                    "case": {
                        "$and": [
                            {"$eq": ["$ns.coll", {"$literal": collection}]},
                            {"$eq": ["$operationType", "insert"]},
                        ]
                    },
                    "then": _partition(policy.insert_partition_field),
                }
            )
        if policy.update_dependencies_for_counts:
            updates.append(
                {
                    "case": {
                        "$and": [
                            {"$eq": ["$ns.coll", {"$literal": collection}]},
                            {"$eq": ["$operationType", "update"]},
                        ]
                    },
                    "then": _changes(),
                }
            )
    projection: BsonDict = {}
    for name, branches in (("partition", partitions), ("changes", updates)):
        if branches:
            projection[name] = {
                "$switch": {"branches": branches, "default": "$$REMOVE"}
            }
    return projection
