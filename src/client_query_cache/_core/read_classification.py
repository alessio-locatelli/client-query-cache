from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pymongo import ReadPreference

from client_query_cache._core.canonical import is_canonicalizable
from client_query_cache._core.find_one_reads import (
    CollationInput,
    find_one_options_cacheable,
)
from client_query_cache._core.read_validation import (
    is_filter_cacheable,
    is_pipeline_cacheable,
    is_projection_cacheable,
)
from client_query_cache._core.snapshots import BypassReason

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


def request_bypass_reason(
    session: object | None,
    read_preference: object,
    read_concern_level: str | None,
    kwargs: Mapping[str, object],
) -> BypassReason | None:
    if session is not None:
        return BypassReason.SESSION
    if read_preference != ReadPreference.PRIMARY or read_concern_level not in {
        None,
        "majority",
    }:
        return BypassReason.READ_PROFILE
    if kwargs:
        return BypassReason.UNSUPPORTED_OPTIONS
    return None


def query_bypass_reason(
    filter_query: Mapping[str, Any] | None,
    projection: Mapping[str, Any] | Sequence[str] | None,
    discriminator: object,
) -> BypassReason | None:
    if not is_filter_cacheable(filter_query):
        return BypassReason.UNSAFE_FILTER
    if not is_projection_cacheable(projection):
        return BypassReason.UNSAFE_PROJECTION
    if not is_canonicalizable(discriminator):
        return BypassReason.UNCANONICALIZABLE_KEY
    return None


def pipeline_bypass_reason(
    pipeline: Sequence[Mapping[str, Any]], discriminator: object
) -> BypassReason | None:
    if not is_pipeline_cacheable(pipeline):
        return BypassReason.UNSAFE_PIPELINE
    if not is_canonicalizable(discriminator):
        return BypassReason.UNCANONICALIZABLE_KEY
    return None


def find_one_bypass_reason(
    filter_query: Mapping[str, Any],
    projection: Mapping[str, Any] | Sequence[str] | None,
    sort: Sequence[tuple[str, int]] | None,
    collation: CollationInput | None,
) -> BypassReason | None:
    if not find_one_options_cacheable(sort, collation):
        return BypassReason.UNSUPPORTED_OPTIONS
    if not is_filter_cacheable(filter_query):
        return BypassReason.UNSAFE_FILTER
    if not is_projection_cacheable(projection):
        return BypassReason.UNSAFE_PROJECTION
    return None
