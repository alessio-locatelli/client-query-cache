from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import pytest

from client_query_cache._core.locking import (
    CapacitySection,
    LockOrderGuard,
    LockOrderViolationError,
    NamespaceLock,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager
    from typing import NoReturn

pytestmark = pytest.mark.unit


def test_lru_section_can_be_entered_after_namespace_section_exits() -> None:
    guard = LockOrderGuard()
    with guard.namespace_section():
        pass
    with guard.lru_section():
        pass


@pytest.mark.parametrize(
    ("outer", "inner"),
    [
        pytest.param(
            lambda guard: guard.namespace_section(),
            lambda guard: guard.lru_section(),
            id="lru_inside_namespace",
        ),
        pytest.param(
            lambda guard: guard.lru_section(),
            lambda guard: guard.namespace_section(),
            id="namespace_inside_lru",
        ),
        pytest.param(
            NamespaceLock,
            LockOrderGuard.lru_section,
            id="lru_inside_namespace_lock",
        ),
        pytest.param(
            LockOrderGuard.lru_section,
            NamespaceLock,
            id="namespace_lock_inside_lru",
        ),
    ],
)
def test_nesting_the_other_section_is_rejected(
    outer: Callable[[LockOrderGuard], AbstractContextManager[None]],
    inner: Callable[[LockOrderGuard], AbstractContextManager[None]],
) -> None:
    guard = LockOrderGuard()
    with outer(guard), pytest.raises(LockOrderViolationError):
        inner(guard).__enter__()


def test_namespace_section_is_reentrant_safe_to_sequence() -> None:
    guard = LockOrderGuard()
    with guard.namespace_section():
        pass
    with guard.namespace_section():
        pass


@pytest.mark.parametrize(
    ("outer", "other"),
    [
        pytest.param(
            LockOrderGuard.namespace_section, LockOrderGuard.lru_section, id="namespace"
        ),
        pytest.param(
            LockOrderGuard.lru_section, LockOrderGuard.namespace_section, id="lru"
        ),
    ],
)
def test_nested_sections_keep_the_outer_guard_until_exit(
    outer: Callable[[LockOrderGuard], AbstractContextManager[None]],
    other: Callable[[LockOrderGuard], AbstractContextManager[None]],
) -> None:
    guard = LockOrderGuard()
    with outer(guard):
        with outer(guard):
            pass
        with pytest.raises(LockOrderViolationError):
            other(guard).__enter__()
    with other(guard):
        pass


@pytest.mark.parametrize(
    "section",
    [LockOrderGuard.namespace_section, LockOrderGuard.lru_section, NamespaceLock],
    ids=["namespace", "lru", "namespace-lock"],
)
def test_exceptions_release_reusable_sections(
    section: Callable[[LockOrderGuard], AbstractContextManager[None]],
) -> None:
    guard = LockOrderGuard()
    with pytest.raises(ValueError, match="abort"), section(guard):
        raise ValueError("abort")
    with guard.namespace_section():
        pass
    with guard.lru_section():
        pass


class _InterruptedAcquire:
    __slots__ = ()

    # Implements a lock-like API that interrupts its acquire call.
    def acquire(self) -> NoReturn:  # noqa: PLR6301
        raise KeyboardInterrupt


def test_interrupted_namespace_acquisition_releases_the_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = LockOrderGuard()
    section = NamespaceLock(guard)
    monkeypatch.setattr(section, "_lock", _InterruptedAcquire())

    with pytest.raises(KeyboardInterrupt):
        section.__enter__()

    with guard.lru_section(), pytest.raises(LockOrderViolationError):
        guard.namespace_section().__enter__()


@pytest.mark.parametrize(
    "storage", [LockOrderGuard.namespace_section, LockOrderGuard.lru_section]
)
def test_capacity_transaction_rejects_storage_lock_inversion(
    storage: Callable[[LockOrderGuard], AbstractContextManager[None]],
) -> None:
    guard = LockOrderGuard()
    capacity = CapacitySection(threading.RLock(), guard)
    with (
        storage(guard),
        pytest.raises(LockOrderViolationError, match="capacity transaction"),
    ):
        capacity.__enter__()
    with capacity, guard.namespace_section():
        pass
