"""Opt into the feature-built owner in an acquisition child before construction."""

from __future__ import annotations

from functools import cache
from typing import TYPE_CHECKING

from client_query_cache.asynchronous import manager as asynchronous
from client_query_cache.synchronous import manager as synchronous

if TYPE_CHECKING:
    from client_query_cache._core.contracts import LocalCacheCore


@cache
def native_core_type() -> type[LocalCacheCore]:
    from client_query_cache._shared_index import local_cache_type  # noqa: PLC0415, PLC2701 - Require the installed experimental binding only when selected.

    return local_cache_type()


def select_native() -> None:
    core = native_core_type()
    # The shared owner imports its reference core directly and is not selected.
    synchronous.CacheCore = core  # type: ignore[assignment,attr-defined]
    asynchronous.CacheCore = core  # type: ignore[assignment,attr-defined]
