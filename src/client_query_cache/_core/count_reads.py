from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from pymongo.collation import Collation

from client_query_cache._core.collation import collation_document

if TYPE_CHECKING:
    from collections.abc import Mapping

_OMITTED = object()


class CountReadOptions(TypedDict):
    cache_options: tuple[object, object, object, object]
    extra_options: dict[str, object]


def count_read_options(kwargs: Mapping[str, object]) -> CountReadOptions:
    extra_options = dict(kwargs)
    skip = extra_options.pop("skip", 0)
    limit = extra_options.pop("limit", _OMITTED)
    collation = extra_options.pop("collation", None)
    hint = extra_options.pop("hint", _OMITTED)
    if isinstance(collation, Collation):
        collation = collation_document(collation)
    cache_options = (skip, limit, collation, hint)
    return {
        "cache_options": cache_options,
        "extra_options": extra_options,
    }
