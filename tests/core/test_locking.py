from __future__ import annotations

import pytest

from mongo_client_cache._core.locking import LockOrderGuard, LockOrderViolationError

pytestmark = pytest.mark.unit


def test_lru_section_can_be_entered_after_namespace_section_exits() -> None:
    guard = LockOrderGuard()
    with guard.namespace_section():
        pass
    with guard.lru_section():
        pass


def test_lru_section_rejects_nesting_inside_namespace_section() -> None:
    guard = LockOrderGuard()
    with (
        guard.namespace_section(),
        pytest.raises(LockOrderViolationError),
        guard.lru_section(),
    ):
        pass


def test_namespace_section_rejects_nesting_inside_lru_section() -> None:
    guard = LockOrderGuard()
    with (
        guard.lru_section(),
        pytest.raises(LockOrderViolationError),
        guard.namespace_section(),
    ):
        pass


def test_namespace_section_is_reentrant_safe_to_sequence() -> None:
    guard = LockOrderGuard()
    with guard.namespace_section():
        pass
    with guard.namespace_section():
        pass
