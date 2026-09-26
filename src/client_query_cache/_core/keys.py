from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple

from client_query_cache._core.canonical import canonicalize
from client_query_cache._core.order_sensitive_keys import order_sensitive_key

if TYPE_CHECKING:
    from client_query_cache._core.canonical import Canonical


class NamespaceId(NamedTuple):
    database: str
    collection: str


@dataclass(frozen=True, slots=True)
class IdentityCacheKey:
    namespace: NamespaceId
    identity: Canonical
    read_shape: Canonical


@dataclass(frozen=True, slots=True)
class NamespaceCacheKey:
    namespace: NamespaceId
    discriminator: Canonical


type CacheKey = IdentityCacheKey | NamespaceCacheKey

type AliasKey = tuple[Canonical, Canonical, Canonical]


def canonical_alias_key(
    definition: object, value: object, collation: object
) -> AliasKey:
    return (
        canonicalize(definition),
        canonicalize(order_sensitive_key(value)),
        canonicalize(collation),
    )
