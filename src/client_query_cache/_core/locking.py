from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator


class LockOrderViolationError(RuntimeError):
    pass


class LockOrderGuard:
    __slots__ = ("_state",)

    def __init__(self) -> None:
        self._state = threading.local()

    @contextmanager
    def namespace_section(self) -> Generator[None]:
        with self._section(entering="in_namespace", forbidden="in_lru"):
            yield

    @contextmanager
    def lru_section(self) -> Generator[None]:
        with self._section(entering="in_lru", forbidden="in_namespace"):
            yield

    @contextmanager
    def _section(self, *, entering: str, forbidden: str) -> Generator[None]:
        if getattr(self._state, forbidden, False):
            message = f"cannot enter {entering!r} section while holding {forbidden!r}"
            raise LockOrderViolationError(message)
        setattr(self._state, entering, True)
        try:
            yield
        finally:
            setattr(self._state, entering, False)
