from __future__ import annotations

import threading
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType


class LockOrderViolationError(RuntimeError):
    pass


class _LockSection(AbstractContextManager[None]):
    __slots__ = ("_entering", "_forbidden", "_state")

    def __init__(
        self,
        state: threading.local,
        entering: Literal["in_namespace", "in_lru"],
        forbidden: Literal["in_namespace", "in_lru"],
    ) -> None:
        self._state = state
        self._entering = entering
        self._forbidden = forbidden

    def __enter__(self) -> None:
        if getattr(self._state, self._forbidden, 0):
            message = (
                f"cannot enter {self._entering!r} section "
                f"while holding {self._forbidden!r}"
            )
            raise LockOrderViolationError(message)
        depth = getattr(self._state, self._entering, 0)
        setattr(self._state, self._entering, depth + 1)

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        depth = getattr(self._state, self._entering)
        setattr(self._state, self._entering, depth - 1)


class LockOrderGuard:
    __slots__ = ("_lru", "_namespace", "_state")

    def __init__(self) -> None:
        state = self._state = threading.local()
        self._namespace = _LockSection(state, "in_namespace", "in_lru")
        self._lru = _LockSection(state, "in_lru", "in_namespace")

    def namespace_section(self) -> _LockSection:
        return self._namespace

    def lru_section(self) -> _LockSection:
        return self._lru

    def assert_outside_storage(self) -> None:
        state = self._state
        if getattr(state, "in_namespace", 0) or getattr(state, "in_lru", 0):
            message = (
                "cannot enter capacity transaction while holding a storage section"
            )
            raise LockOrderViolationError(message)


class CapacitySection(AbstractContextManager[None]):
    __slots__ = ("_guard", "_lock", "_state")

    def __init__(self, lock: threading.RLock, guard: LockOrderGuard) -> None:
        self._lock = lock
        self._guard = guard
        self._state = threading.local()

    def __enter__(self) -> None:
        self._guard.assert_outside_storage()
        self._lock.acquire()
        depth = getattr(self._state, "depth", 0)
        if depth == 0:
            self._state.retired = []
        self._state.depth = depth + 1

    def retire(self, *objects: object) -> None:
        self._state.retired.extend(objects)

    def set_completion(self, notification: Callable[[], None]) -> None:
        # One final publication owns the outer transaction's completion notice.
        self._state.completion = notification

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self._state.depth -= 1
        if self._state.depth:
            self._lock.release()
            return
        retired = self._state.retired
        self._state.retired = None
        completion = getattr(self._state, "completion", None)
        self._state.completion = None
        self._lock.release()
        retired.clear()
        if completion is not None:
            completion()


class NamespaceLock(AbstractContextManager[None]):
    __slots__ = ("_lock", "_section")

    def __init__(self, guard: LockOrderGuard) -> None:
        self._section = guard.namespace_section()
        self._lock = threading.Lock()

    def __enter__(self) -> None:
        self._section.__enter__()
        try:
            self._lock.acquire()
        except BaseException:
            self._section.__exit__(None, None, None)
            raise

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            self._lock.release()
        finally:
            self._section.__exit__(exc_type, exc_value, traceback)
