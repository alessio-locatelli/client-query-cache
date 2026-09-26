from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from client_query_cache._core.canonical import Canonical
    from client_query_cache._core.keys import NamespaceId


class AdmissionOutcome(enum.Enum):
    ADMITTED = "admitted"
    DECLINED_OVERSIZE = "declined_oversize"
    DECLINED_STALE = "declined_stale"
    DECLINED_UNAVAILABLE = "declined_unavailable"
    DECLINED_UNENCODABLE = "declined_unencodable"


@dataclass(eq=False, slots=True)
class CacheEntry:
    generation_key: tuple[int, ...]
    weight: int
    value: bytes
    namespace: NamespaceId
    identity: Canonical | None


@dataclass(frozen=True, slots=True)
class LookupResult:
    hit: bool
    value: Any = None
