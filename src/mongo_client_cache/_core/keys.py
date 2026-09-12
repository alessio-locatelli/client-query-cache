from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple

from mongo_client_cache._core.canonical import canonicalize

if TYPE_CHECKING:
    from mongo_client_cache._core.canonical import Canonical


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
    return (canonicalize(definition), canonicalize(value), canonicalize(collation))
