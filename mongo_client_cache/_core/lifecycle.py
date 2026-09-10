from __future__ import annotations

import enum


class CacheLifecycleState(enum.Enum):
    ACTIVE = "active"
    CLOSED = "closed"
