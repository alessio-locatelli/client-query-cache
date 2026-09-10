from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mongo_client_cache._core.canonical import Canonical
    from mongo_client_cache._core.keys import NamespaceId


class AdmissionOutcome(enum.Enum):
    ADMITTED = "admitted"
    DECLINED_OVERSIZE = "declined_oversize"
    DECLINED_STALE = "declined_stale"


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
