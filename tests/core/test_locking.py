from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from client_query_cache._core.locking import LockOrderGuard, LockOrderViolationError

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager

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
    [LockOrderGuard.namespace_section, LockOrderGuard.lru_section],
    ids=["namespace", "lru"],
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
