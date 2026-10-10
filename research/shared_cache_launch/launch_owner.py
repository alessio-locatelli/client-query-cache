# ruff: noqa: INP001 - Shared owner launcher for the research launch smoke.
from __future__ import annotations

import os
from typing import TYPE_CHECKING

from benchmarks.stream_cost.shared_cache.coordinator import OwnerConfig, TransportLimits
from benchmarks.stream_cost.shared_cache.owner import owner_main
from benchmarks.stream_cost.shared_cache.window import attachment_for

if TYPE_CHECKING:
    from multiprocessing.connection import Connection
    from multiprocessing.context import SpawnContext
    from multiprocessing.process import BaseProcess

    from benchmarks.stream_cost.shared_cache.attachment import AttachmentConfig

LIMITS = TransportLimits(
    rpc_deadline_seconds=0.5,
    progress_expiry_seconds=3.0,
    queued_bytes_per_connection=4 * 1024 * 1024,
    requests_per_connection=256,
    connections=64,
    captures=4096,
    capture_seconds=30.0,
    frame_overhead_bytes=65_536,
)


def config_from_environment() -> OwnerConfig:
    return OwnerConfig(
        socket_path=os.environ["SHARED_CACHE_SOCKET"],
        capability=bytes.fromhex(os.environ["SHARED_CACHE_CAPABILITY"]),
        mongodb_uri=os.environ["SHARED_CACHE_MONGODB_URI"],
        client_options={"directConnection": True},
        databases=(os.environ["SHARED_CACHE_DATABASE"],),
        budget_bytes=16 * 1024 * 1024,
        max_entry_bytes=1024 * 1024,
        max_await_time_ms=1000,
        limits=LIMITS,
        lag_capture=(1, 1, 0),
    )


def attachment_from_environment() -> AttachmentConfig:
    return attachment_for(config_from_environment())


def owner_from_environment(context: SpawnContext) -> tuple[BaseProcess, Connection]:
    parent, child = context.Pipe()
    process = context.Process(
        target=owner_main, args=(config_from_environment(), child)
    )
    process.start()
    child.close()
    ready = parent.recv()
    if ready["kind"] != "ready":
        message = f"shared cache owner failed to start: {ready}"
        raise RuntimeError(message)
    return process, parent
