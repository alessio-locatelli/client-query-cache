from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pymongo.collation import Collation

from client_query_cache._core.collation import normalize_collation
from client_query_cache._core.order_sensitive_keys import (
    order_sensitive_discriminator_key,
)
from client_query_cache._core.read_validation import (
    is_filter_cacheable,
    is_projection_cacheable,
)

type CollationInput = Collation | Mapping[str, Any]

_COLLATION_FIELDS = frozenset(
    {
        "locale",
        "caseLevel",
        "caseFirst",
        "strength",
        "numericOrdering",
        "alternate",
        "maxVariable",
        "normalization",
        "backwards",
    }
)


def normalize_find_one_filter(filter_query: object) -> Mapping[str, Any]:
    if filter_query is None:
        return {}
    if isinstance(filter_query, Mapping):
        return filter_query
    return {"_id": filter_query}


def find_one_options_cacheable(
    filter_query: Mapping[str, Any],
    projection: Mapping[str, Any] | Sequence[str] | None,
    sort: Sequence[tuple[str, int]] | None,
    collation: CollationInput | None,
) -> bool:
    if not is_filter_cacheable(filter_query) or not is_projection_cacheable(projection):
        return False
    if sort is not None and (
        not isinstance(sort, (list, tuple))
        or any(
            not isinstance(pair, (list, tuple))
            or len(pair) != 2
            or not isinstance(pair[0], str)
            or type(pair[1]) is not int
            or pair[1] not in {-1, 1}
            for pair in sort
        )
    ):
        return False
    if collation is None:
        return True
    document = collation.document if isinstance(collation, Collation) else collation
    if not isinstance(document, dict) or not document.keys() <= _COLLATION_FIELDS:
        return False
    try:
        validated = Collation(**document).document
    except TypeError, ValueError:
        return False
    if not validated["locale"]:
        return False
    if validated["locale"] == "simple":
        return len(validated) == 1
    for field, choices in (
        ("strength", (1, 2, 3, 4, 5)),
        ("caseFirst", ("upper", "lower", "off")),
        ("alternate", ("non-ignorable", "shifted")),
        ("maxVariable", ("punct", "space")),
    ):
        if field in validated and validated[field] not in choices:
            return False
    return True


def effective_find_one_collation(
    collation: CollationInput | None,
    default_collation: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    if collation is None:
        return default_collation
    document = collation.document if isinstance(collation, Collation) else collation
    return normalize_collation(document)


def find_one_read_shape(
    projection: Mapping[str, Any] | Sequence[str] | None,
    sort: Sequence[tuple[str, int]] | None,
    effective_collation: Mapping[str, Any] | None,
    codec_identity: object,
) -> object:
    return order_sensitive_discriminator_key(
        ("find_one", projection, sort, effective_collation, codec_identity)
    )


def generic_find_one_discriminator(
    filter_query: Mapping[str, Any],
    read_shape: object,
    index_generation: int,  # Can be zero.
) -> object:
    return order_sensitive_discriminator_key(
        ("find_one_generic", filter_query, read_shape, index_generation)
    )
