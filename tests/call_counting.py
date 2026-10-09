from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


@dataclass(slots=True)
class CallCounter:
    count: int = 0


def count_current_thread_calls(
    monkeypatch: pytest.MonkeyPatch, owner: object, name: str
) -> CallCounter:
    original = getattr(owner, name)
    thread = threading.get_ident()
    counter = CallCounter()

    def counted(*args: object, **kwargs: object) -> object:
        if threading.get_ident() == thread:  # pragma: no branch - CI-only races
            counter.count += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(owner, name, counted)
    return counter
