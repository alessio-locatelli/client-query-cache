from __future__ import annotations

import threading
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
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
    __slots__ = ("_lru", "_namespace")

    def __init__(self) -> None:
        state = threading.local()
        self._namespace = _LockSection(state, "in_namespace", "in_lru")
        self._lru = _LockSection(state, "in_lru", "in_namespace")

    def namespace_section(self) -> _LockSection:
        return self._namespace

    def lru_section(self) -> _LockSection:
        return self._lru
