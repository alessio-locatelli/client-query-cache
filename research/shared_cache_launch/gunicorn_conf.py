# ruff: noqa: INP001 - Gunicorn configuration for the research launch smoke.
from __future__ import annotations

import multiprocessing
from typing import TYPE_CHECKING

from research.shared_cache_launch.launch_owner import owner_from_environment

if TYPE_CHECKING:
    from multiprocessing.process import BaseProcess

    from gunicorn.arbiter import Arbiter

workers = 2
max_requests = 5
max_requests_jitter = 0
_owner: list[tuple[BaseProcess, object]] = []


def on_starting(_server: Arbiter) -> None:
    context = multiprocessing.get_context("spawn")
    _owner.append(owner_from_environment(context))


def on_exit(_server: Arbiter) -> None:
    for process, control in _owner:
        control.send("close")  # type: ignore[attr-defined]
        control.recv()  # type: ignore[attr-defined]
        process.join(15)
