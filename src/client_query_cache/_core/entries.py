from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any


class AdmissionOutcome(enum.Enum):
    ADMITTED = "admitted"
    DECLINED_OVERSIZE = "declined_oversize"
    DECLINED_STALE = "declined_stale"
    DECLINED_UNAVAILABLE = "declined_unavailable"
    DECLINED_UNENCODABLE = "declined_unencodable"
    DECLINED_RETENTION = "declined_retention"


@dataclass(frozen=True, slots=True)
class LookupResult:
    hit: bool
    value: Any = None
    deferred_miss: bool = False


_MISS = LookupResult(hit=False)
_DEFERRED_MISS = LookupResult(hit=False, deferred_miss=True)
