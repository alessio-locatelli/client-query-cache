"""Parent-owned cache servers for trusted workers on one Linux host."""

from __future__ import annotations

import logging
import multiprocessing
import os
import platform
import secrets
import shutil
import sys
import tempfile
import weakref
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Self

from annotated_types import Ge, Le

from client_query_cache._core.errors import CacheClosedError, CacheConfigurationError
from client_query_cache._core.manager import CacheCoreConfig
from client_query_cache._core.stream_cost import DEFAULT_LAG_CAPTURE_WINDOW_CONFIG
from client_query_cache._shared.adapters import SharedCacheStatistics
from client_query_cache._shared.attachment import AttachmentConfig
from client_query_cache._shared.coordinator import (
    OwnerConfig,
    SharedCacheOwner,
    TransportLimits,
)
from client_query_cache._shared.shared_index import SharedIndexLimits
from client_query_cache._types import PositiveInt

if TYPE_CHECKING:
    from collections.abc import Mapping
    from multiprocessing.connection import Connection
    from multiprocessing.process import BaseProcess

__all__ = [
    "SharedCacheConfig",
    "SharedCacheConnection",
    "SharedCacheServer",
    "SharedCacheStatistics",
]

_SERVERS: weakref.WeakSet[SharedCacheServer] = weakref.WeakSet()
_LOGGER = logging.getLogger(__name__)
_MAX_NAMESPACES = (1 << 32) - 1
_MAX_ARENA_BYTES = _MAX_NAMESPACES * 8
_MAX_SLOTS = 1 << ((sys.maxsize // 64).bit_length() - 1)


def _detach_servers_after_fork() -> (
    None
):  # pragma: lax no cover - Runs before child coverage starts.
    for server in tuple(_SERVERS):
        server._detach_after_fork()  # noqa: SLF001 - Registry callback detaches inherited server resources.


# ast-grep-ignore: no-import-time-execution
os.register_at_fork(after_in_child=_detach_servers_after_fork)


@dataclass(frozen=True, slots=True)
class SharedCacheConfig:
    """Finite owner capacities; the cache budget is not a total RSS limit."""

    budget_bytes: PositiveInt = 64 * 1024 * 1024
    max_entry_bytes: PositiveInt = 1024 * 1024
    slots: Annotated[PositiveInt, Le(_MAX_SLOTS)] = 65_536
    arena_bytes: Annotated[PositiveInt, Le(_MAX_ARENA_BYTES)] = 80 * 1024 * 1024
    namespaces: Annotated[PositiveInt, Le(_MAX_NAMESPACES)] = 1024
    connections: Annotated[PositiveInt, Ge(2)] = 256

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                message = f"{name} must be a positive built-in integer"
                raise CacheConfigurationError(message)
        if self.slots & (self.slots - 1) or self.slots > _MAX_SLOTS:
            raise CacheConfigurationError("slots must be a supported power of two")
        if self.arena_bytes > _MAX_ARENA_BYTES:
            raise CacheConfigurationError("arena_bytes exceeds the native layout limit")
        if self.namespaces > _MAX_NAMESPACES:
            raise CacheConfigurationError("namespaces exceeds the native layout limit")
        if self.connections < 2:
            raise CacheConfigurationError(
                "connections must allow at least two connections"
            )
        CacheCoreConfig(
            budget_bytes=self.budget_bytes,
            max_entry_bytes=self.max_entry_bytes,
            max_namespaces=self.namespaces,
        )
        if self.max_entry_bytes > self.arena_bytes:
            raise CacheConfigurationError("max_entry_bytes must not exceed arena_bytes")


_DEFAULT_CONFIG = SharedCacheConfig()


@dataclass(frozen=True, slots=True)
class SharedCacheConnection:
    """Picklable access to all configured databases for trusted workers."""

    _attachment: AttachmentConfig = field(repr=False)


def _owner_main(config: OwnerConfig, control: Connection) -> None:
    owner: SharedCacheOwner | None = None
    parent_lost = False
    try:  # noqa: PLW0717 - Sanitize failures across owner initialization and serving.
        owner = SharedCacheOwner(config)
        owner.bind()
        control.send("ready")
        try:
            owner.serve(control, lambda _request: None)
        except EOFError:
            parent_lost = True
    except Exception:  # noqa: BLE001 - Process boundary reports failure without exposing connection credentials.
        _LOGGER.error("shared cache owner failed; attached reads will bypass caching")  # noqa: TRY400 - Tracebacks can reveal connection credentials.
        try:
            control.send("failed")
        except BrokenPipeError:
            pass
    finally:
        if owner is not None:
            owner.close()
        control.close()
        if parent_lost:
            path = Path(config.socket_path)
            path.with_suffix(".lock").unlink(missing_ok=True)
            path.parent.rmdir()


class SharedCacheServer:
    """Start in the application parent, then pass ``connection`` to its workers."""

    __slots__ = (
        "__weakref__",
        "_config",
        "_control",
        "_directory",
        "_directory_cleanup",
        "_pid",
        "_process",
        "connection",
    )

    def __init__(
        self,
        mongodb_uri: str,
        databases: tuple[str, ...],
        *,
        config: SharedCacheConfig = _DEFAULT_CONFIG,
        client_options: Mapping[str, object] | None = None,
    ) -> None:
        if platform.system() != "Linux" or platform.machine() not in {
            "x86_64",
            "aarch64",
        }:
            raise CacheConfigurationError("shared caches require Linux x86-64 or ARM64")
        if not databases or any(
            not isinstance(name, str) or not name for name in databases
        ):
            raise CacheConfigurationError(
                "databases must contain distinct nonempty names"
            )
        if len(set(databases)) != len(databases):
            raise CacheConfigurationError(
                "databases must contain distinct nonempty names"
            )
        self._pid = os.getpid()
        self._process: BaseProcess | None = None
        self._control: Connection | None = None
        self._directory = Path(tempfile.mkdtemp(prefix="client-query-cache-"))
        self._directory_cleanup = weakref.finalize(self, shutil.rmtree, self._directory)
        _SERVERS.add(self)
        path = str(self._directory / "owner.sock")
        limits = TransportLimits(
            rpc_deadline_seconds=0.25,
            progress_expiry_seconds=3.0,
            queued_bytes_per_connection=config.max_entry_bytes + 65_536,
            requests_per_connection=256,
            connections=config.connections,
            captures=4096,
            capture_seconds=30.0,
            frame_overhead_bytes=65_536,
        )
        self._config = OwnerConfig(
            socket_path=path,
            capability=secrets.token_bytes(32),
            mongodb_uri=mongodb_uri,
            client_options={} if client_options is None else dict(client_options),
            databases=tuple(databases),
            budget_bytes=config.budget_bytes,
            max_entry_bytes=config.max_entry_bytes,
            max_await_time_ms=100,
            limits=limits,
            lag_capture=(
                DEFAULT_LAG_CAPTURE_WINDOW_CONFIG.window_count,
                DEFAULT_LAG_CAPTURE_WINDOW_CONFIG.events_per_window,
                DEFAULT_LAG_CAPTURE_WINDOW_CONFIG.min_separation_events,
            ),
            shared_index=SharedIndexLimits(
                slots=config.slots,
                arena_bytes=config.arena_bytes,
                namespaces=config.namespaces,
                ring_tokens=4096,
                local_miss_admission=True,
                native_admission_queue=True,
            ),
        )
        self.connection = SharedCacheConnection(
            AttachmentConfig(
                socket_path=path,
                capability=self._config.capability,
                budget_bytes=config.budget_bytes,
                max_entry_bytes=config.max_entry_bytes,
                max_await_time_ms=self._config.max_await_time_ms,
                rpc_deadline_seconds=limits.rpc_deadline_seconds,
                frame_limit=self._config.frame_limit,
                max_namespaces=config.namespaces,
            )
        )
        try:
            self._start()
        except BaseException:
            self.close()
            raise

    def _check_parent(self) -> None:
        if os.getpid() != self._pid:
            raise CacheClosedError("the shared server belongs to its creating parent")

    def _detach_after_fork(self) -> None:  # pragma: lax no cover - Fork child.
        if self._control is not None:
            self._control.close()
        self._directory_cleanup.detach()

    def _start(self) -> None:
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        process = context.Process(target=_owner_main, args=(self._config, child))
        process.daemon = True
        self._control = parent
        self._process = process
        try:
            process.start()
        finally:
            child.close()
        if not parent.poll(10):
            raise CacheConfigurationError("shared cache owner startup timed out")
        try:
            ready = parent.recv()
        except EOFError as error:
            raise CacheConfigurationError(
                "shared cache owner failed to start"
            ) from error
        if ready != "ready":
            raise CacheConfigurationError("invalid shared cache owner startup reply")

    def _stop(self) -> None:
        process, control = self._process, self._control
        if control is not None:
            assert process is not None
            if process.is_alive():
                try:
                    control.send("close")
                except BrokenPipeError:  # pragma: lax no cover - Peer exit race.
                    pass
            control.close()
        if process is not None and process.pid is not None:
            process.join(5)
            if process.is_alive():
                process.terminate()
                process.join(2)
            if process.is_alive():
                process.kill()
                process.join(2)
            if (
                process.is_alive()
            ):  # pragma: lax no cover - Requires the kernel to refuse SIGKILL.
                raise CacheClosedError("shared cache owner could not be reaped")
            process.close()
        self._process = None
        self._control = None

    def restart(self) -> None:
        """Replace the owner with fresh state.

        Raises:
            CacheClosedError: The server is closed or belongs to another parent.
        """
        self._check_parent()
        if self._process is None:
            raise CacheClosedError("the shared cache server is closed")
        self._stop()
        try:
            self._start()
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        """Reap the owner and remove its private endpoint. Safe to repeat."""
        self._check_parent()
        try:
            self._stop()
        finally:
            self._directory_cleanup()

    def __enter__(self) -> Self:
        self._check_parent()
        if self._process is None:
            raise CacheClosedError("the shared cache server is closed")
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
