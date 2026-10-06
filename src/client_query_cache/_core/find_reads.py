from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from client_query_cache._core.canonical import canonicalize
from client_query_cache._core.order_sensitive_keys import (
    order_sensitive_discriminator_key,
)
from client_query_cache._core.query_filters import find_filter_key

if TYPE_CHECKING:
    from client_query_cache._core.canonical import Canonical


@dataclass(frozen=True, slots=True)
class FindSource:
    family: int  # A compact hash, possibly zero; collisions require key equality.
    limit: int  # Zero denotes unlimited; negative and boolean limits are excluded.


@dataclass(frozen=True, slots=True)
class FindReadShape:
    family: object
    limit: int  # Zero and negative limits retain exact-only lookup.

    @property
    def discriminator(self) -> object:
        return (self.family, self.limit)

    @property
    def source(self) -> FindSource | None:
        if isinstance(self.limit, bool) or self.limit < 0:
            return None
        return FindSource(hash(canonicalize(self.family)), self.limit)


def find_discriminator(
    family: Canonical,
    limit: int,  # Zero and negative limits retain exact identity.
) -> Canonical:
    # Reuse the already canonical family without copying its query tree.
    return canonicalize((family, limit))


def find_read_shape(
    filter_document: object,
    projection: object,
    ordering: object,
    skip: int,  # Zero means no skipped documents.
    limit: int,  # Zero and negative limits use native semantics.
    *,
    collation: object,
    codec: object,
) -> FindReadShape:
    return FindReadShape(
        family=order_sensitive_discriminator_key(
            (
                "find",
                find_filter_key(filter_document),
                projection,
                ordering,
                skip,
                collation,
                codec,
            )
        ),
        limit=limit,
    )
