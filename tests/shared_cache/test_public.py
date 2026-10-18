from __future__ import annotations

import asyncio
import errno
import importlib
import multiprocessing
import os
import platform
import signal
import socket
import threading
import time
from collections import UserDict
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, override
from unittest.mock import AsyncMock, Mock

import psutil
import pytest
from bson.codec_options import CodecOptions, TypeDecoder, TypeRegistry
from bson.timestamp import Timestamp
from bson.tz_util import FixedOffset
from pymongo import AsyncMongoClient, MongoClient, ReadPreference
from pymongo.asynchronous.cursor import AsyncCursor
from pymongo.collation import Collation
from pymongo.read_concern import ReadConcern
from pymongo.synchronous.cursor import Cursor

from client_query_cache import (
    CacheClosedError,
    CacheConfigurationError,
    SharedCacheConfig,
    SharedCacheManager,
    SharedCacheServer,
    shared,
)
from client_query_cache._core.snapshots import BypassReason
from client_query_cache._shared import adapters, attachment, wire
from client_query_cache._shared.attachment import (
    AsyncLocalIndex,
    AttachmentConfig,
    AttachmentConfigurationError,
    ControlAttachment,
)
from client_query_cache._types import BsonDict, PositiveInt
from client_query_cache.asynchronous import (
    SharedCachedCollection as AsyncSharedCachedCollection,
)
from client_query_cache.asynchronous import (
    SharedCacheManager as AsyncSharedCacheManager,
)
from tests.shared_cache.conftest import wait_for

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Buffer, Callable, Iterator
    from multiprocessing.connection import Connection
    from typing import Any

    from faker import Faker

    from client_query_cache._core.find_one_reads import CollationInput
    from client_query_cache.asynchronous import SharedCachedCollection as AsyncView
    from client_query_cache.shared import SharedCacheConnection
    from client_query_cache.synchronous import SharedCachedCollection as SyncView
    from tests.conftest import DatabaseName, MongoDbUri

pytestmark = pytest.mark.integration


def _spawned_read(
    connection: SharedCacheConnection, uri: str, database: str, pipe: Connection
) -> None:
    with (
        MongoClient[BsonDict](uri) as client,
        SharedCacheManager(client, connection) as manager,
    ):
        document = manager[database]["catalogue"].find_one({"_id": 0})
        pipe.send((document, manager.snapshot().hits))
    pipe.close()


def _abrupt_parent(
    uri: str, pipe: Connection
) -> None:  # pragma: lax no cover - Forced process exit discards child coverage.
    server = SharedCacheServer(uri, ("application",))
    assert server._process is not None
    pipe.send((server.connection._attachment.socket_path, server._process.pid))
    pipe.recv()
    os._exit(0)


def _abrupt_owner(
    _config: object, _pipe: Connection
) -> None:  # pragma: lax no cover - Forced process exit discards child coverage.
    os._exit(1)


def _stalled_startup(
    _config: object, _pipe: Connection
) -> None:  # pragma: lax no cover - Forced process exit discards child coverage.
    os.kill(os.getpid(), signal.SIGSTOP)


@pytest.fixture
def lost_control() -> Iterator[Connection]:
    parent, child = multiprocessing.get_context("spawn").Pipe()
    parent.close()
    yield child
    child.close()


def test_startup_failure_after_parent_loss_stays_sanitized(
    server: SharedCacheServer,
    lost_control: Connection,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config = replace(server._config, mongodb_uri="invalid://private-deployment")
    shared._owner_main(config, lost_control)
    assert lost_control.closed
    assert "shared cache owner failed" in caplog.text
    assert "private-deployment" not in caplog.text


@pytest.fixture
def abrupt_parent(mongodb_uri: MongoDbUri) -> Iterator[Connection]:
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_abrupt_parent, args=(mongodb_uri, child))
    process.start()
    child.close()
    yield parent
    parent.close()
    process.join(10)
    if process.is_alive():  # pragma: lax no cover - Cleanup after a failed worker.
        process.kill()
        process.join(5)
    assert process.exitcode == 0
    process.close()


@pytest.fixture
def stopped_owner(server: SharedCacheServer) -> Iterator[None]:
    assert server._process is not None
    pid = server._process.pid
    assert pid is not None
    os.kill(pid, signal.SIGSTOP)
    yield
    os.kill(pid, signal.SIGCONT)


@pytest.fixture
def spawned_worker(
    server: SharedCacheServer, mongodb_uri: MongoDbUri, seeded_database: DatabaseName
) -> Iterator[Connection]:
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(
        target=_spawned_read,
        args=(server.connection, mongodb_uri, seeded_database, child),
    )
    process.start()
    child.close()
    yield parent
    parent.close()
    process.join(10)
    if process.is_alive():  # pragma: lax no cover - Cleanup after a failed worker.
        process.kill()
        process.join(5)
    assert process.exitcode == 0
    process.close()


@pytest.fixture
def client(mongodb_uri: MongoDbUri) -> Iterator[MongoClient[BsonDict]]:
    with MongoClient[BsonDict](mongodb_uri, directConnection=True) as client:
        yield client


@pytest.fixture
async def async_client(
    mongodb_uri: MongoDbUri,
) -> AsyncIterator[AsyncMongoClient[BsonDict]]:
    async with AsyncMongoClient[BsonDict](mongodb_uri) as client:
        yield client


@pytest.fixture
async def async_attached(
    server: SharedCacheServer, async_client: AsyncMongoClient[BsonDict]
) -> AsyncIterator[AsyncSharedCacheManager[BsonDict]]:
    manager = await AsyncSharedCacheManager.attach(async_client, server.connection)
    async with manager:
        yield manager


@pytest.fixture
def sync_attached(
    server: SharedCacheServer, client: MongoClient[BsonDict]
) -> Iterator[SharedCacheManager[BsonDict]]:
    with SharedCacheManager(client, server.connection) as manager:
        yield manager


@pytest.fixture
def server(
    mongodb_uri: MongoDbUri,
    seeded_database: DatabaseName,
    request: pytest.FixtureRequest,
) -> Iterator[SharedCacheServer]:
    with SharedCacheServer(
        mongodb_uri,
        (seeded_database,),
        config=SharedCacheConfig(
            budget_bytes=1024 * 1024,
            max_entry_bytes=65_536,
            arena_bytes=2 * 1024 * 1024,
            slots=256,
            connections=getattr(request, "param", 16),
        ),
        client_options={"directConnection": True, "serverSelectionTimeoutMS": 5000},
    ) as owner:
        yield owner


class UnhashableIdentityDecoder(TypeDecoder):
    bson_type = int

    @override
    def transform_bson(self, value: int) -> set[int]:
        return {value}


@pytest.fixture
def worker_type_registry(request: pytest.FixtureRequest) -> TypeRegistry:
    decoders = [UnhashableIdentityDecoder()] if getattr(request, "param", False) else []
    return TypeRegistry(decoders)


@pytest.fixture(params=("sync", "async"))
async def manager(
    request: pytest.FixtureRequest,
    initial_owner_outage: SharedCacheServer,
    mongodb_uri: MongoDbUri,
    worker_type_registry: TypeRegistry,
) -> AsyncIterator[SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict]]:
    connection = initial_owner_outage.connection
    if request.param == "sync":
        client: MongoClient[BsonDict] = MongoClient(
            mongodb_uri, directConnection=True, type_registry=worker_type_registry
        )
        with client, SharedCacheManager(client, connection) as attached:
            yield attached
    else:
        aclient: AsyncMongoClient[BsonDict] = AsyncMongoClient(
            mongodb_uri, directConnection=True, type_registry=worker_type_registry
        )
        async with (
            aclient,
            AsyncSharedCacheManager(aclient, connection) as async_attached,
        ):
            yield async_attached


@pytest.fixture
def unix_connect_fault(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[PositiveInt, Callable[[], None]], None]:
    def install(position: PositiveInt, action: Callable[[], None]) -> None:
        original = socket.socket.connect
        connections = 0

        def connect(
            sock: socket.socket, address: tuple[object, ...] | str | Buffer | int
        ) -> None:
            nonlocal connections
            if sock.family == socket.AF_UNIX:
                connections += 1
                if connections == position:
                    action()
            original(sock, address)

        monkeypatch.setattr(socket.socket, "connect", connect)

    return install


@pytest.fixture
def initial_owner_outage(
    request: pytest.FixtureRequest,
    server: SharedCacheServer,
    unix_connect_fault: Callable[[PositiveInt, Callable[[], None]], None],
) -> SharedCacheServer:
    outage = getattr(request, "param", None)
    if outage is not None:
        process = server._process
        assert process is not None
        assert process.pid is not None

        def terminate() -> None:
            process.kill()
            process.join(5)

        if outage == "control-lost":
            unix_connect_fault(2, terminate)
        elif outage == "crashed":
            terminate()
        else:
            os.kill(process.pid, signal.SIGSTOP)
    return server


async def _read(
    view: SyncView[BsonDict] | AsyncView[BsonDict],
    filter_query: object,
    *,
    collation: CollationInput | None = None,
    **kwargs: object,
) -> BsonDict | None:
    if isinstance(view, AsyncSharedCachedCollection):
        return await view.find_one(filter_query, None, collation=collation, **kwargs)
    return view.find_one(filter_query, None, collation=collation, **kwargs)


async def _warm(
    manager: SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict],
    view: SyncView[BsonDict] | AsyncView[BsonDict],
) -> None:
    deadline = time.monotonic() + 10
    while manager.snapshot().hits == 0:
        assert await _read(view, {"_id": 0}) is not None
        assert time.monotonic() < deadline
        await asyncio.sleep(0.02)


async def test_public_shared_reads_invalidate_and_reconnect(
    manager: SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict],
    server: SharedCacheServer,
    seeded_database: DatabaseName,
    client: MongoClient[BsonDict],
) -> None:
    view = manager[seeded_database]["catalogue"]
    await _warm(manager, view)
    assert manager.local is not None
    incarnation = manager.local.incarnation
    client[seeded_database].catalogue.update_one(
        {"_id": 0}, {"$set": {"public_marker": True}}
    )
    deadline = time.monotonic() + 10
    while True:
        document = await _read(view, {"_id": 0})
        assert document is not None
        if "public_marker" in document:
            break
        assert time.monotonic() < deadline
        await asyncio.sleep(0.02)
    server.restart()
    deadline = time.monotonic() + 10
    while manager.local.incarnation == incarnation:
        assert await _read(view, {"_id": 0}) == document
        assert time.monotonic() < deadline
        await asyncio.sleep(0.02)


@pytest.mark.parametrize(
    "collation", [{"locale": "en", "strength": 2}, Collation("en", strength=2)]
)
async def test_explicit_non_simple_collation_uses_the_driver(
    manager: SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict],
    seeded_database: DatabaseName,
    client: MongoClient[BsonDict],
    collation: CollationInput,
) -> None:
    view = manager[seeded_database]["catalogue"]
    await _warm(manager, view)
    client[seeded_database].catalogue.insert_one({"_id": "MixedCase"})
    before = manager.snapshot()
    assert await _read(view, {"_id": "mixedcase"}, collation=collation) == {
        "_id": "MixedCase"
    }
    assert manager.snapshot().hits == before.hits
    assert manager.snapshot().bypasses == before.bypasses + 1


@pytest.mark.parametrize("collation", [{"locale": "simple"}, Collation("simple")])
async def test_explicit_simple_collation_reuses_the_shared_hit(
    manager: SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict],
    seeded_database: DatabaseName,
    collation: CollationInput,
) -> None:
    view = manager[seeded_database]["catalogue"]
    await _warm(manager, view)
    before = manager.snapshot().hits
    assert await _read(view, {"_id": 0}, collation=collation) is not None
    assert manager.snapshot().hits == before + 1


class _IdentityField(str):  # noqa: FURB189 - Exercise real string-subclass keys, which BSON accepts.
    __slots__ = ()


@pytest.mark.parametrize(
    ("filter_query", "shared_hit"),
    [
        pytest.param(UserDict({"_id": 0}), True, id="mapping"),
        pytest.param({_IdentityField("_id"): 0}, True, id="field-subclass"),
        pytest.param({"_id": {"$eq": 0}}, False, id="equality-operator"),
    ],
)
async def test_identity_forms_preserve_shared_scope(
    manager: SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict],
    seeded_database: DatabaseName,
    filter_query: object,
    shared_hit: bool,
) -> None:
    view = manager[seeded_database]["catalogue"]
    await _warm(manager, view)
    before = manager.snapshot()
    assert await _read(view, filter_query) is not None
    assert manager.snapshot().hits == before.hits + int(shared_hit)
    assert manager.snapshot().bypasses == before.bypasses
    assert manager.snapshot().misses == before.misses + int(not shared_hit)


async def test_default_identity_reads_with_a_hint_use_the_driver(
    manager: SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict],
    seeded_database: DatabaseName,
) -> None:
    view = manager[seeded_database]["catalogue"]
    await _warm(manager, view)
    before = manager.snapshot()
    assert await _read(view, {"_id": 0}, hint="_id_") is not None
    assert manager.snapshot().hits == before.hits
    assert manager.snapshot().bypasses == before.bypasses + 1
    assert manager.observation.bypasses["unsupported_options"] == 1


@pytest.fixture
async def bound_shared_view(
    manager: SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict],
    seeded_database: DatabaseName,
) -> AsyncIterator[SyncView[BsonDict] | AsyncView[BsonDict]]:
    view = manager[seeded_database]["catalogue"]
    await _warm(manager, view)
    if isinstance(manager, AsyncSharedCacheManager):
        async with manager.client.start_session().bind():
            yield view
    else:
        with manager.client.start_session().bind():
            yield view


async def test_default_identity_reads_respect_bound_sessions(
    manager: SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict],
    bound_shared_view: SyncView[BsonDict] | AsyncView[BsonDict],
) -> None:
    before = manager.snapshot()
    assert await _read(bound_shared_view, {"_id": 0}) is not None
    assert manager.snapshot().hits == before.hits
    assert manager.snapshot().bypasses == before.bypasses + 1
    assert manager.observation.bypasses["session"] == 1


@dataclass(init=False)
class _UnhashableUTC(FixedOffset):
    pass


@pytest.mark.parametrize(
    ("options", "reason"),
    [
        pytest.param(
            {"read_preference": ReadPreference.SECONDARY_PREFERRED},
            BypassReason.READ_PROFILE,
            id="secondary",
        ),
        pytest.param(
            {"read_concern": ReadConcern("local")},
            BypassReason.READ_PROFILE,
            id="local-concern",
        ),
        pytest.param(
            {
                "codec_options": CodecOptions(
                    tz_aware=True, tzinfo=_UnhashableUTC(0, "UTC")
                )
            },
            BypassReason.UNCANONICALIZABLE_KEY,
            id="uncanonicalizable-codec",
        ),
    ],
)
async def test_default_identity_reads_preserve_policy_and_codec_bypasses(
    manager: SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict],
    seeded_database: DatabaseName,
    options: dict[str, Any],
    reason: BypassReason,
) -> None:
    await _warm(manager, manager[seeded_database]["catalogue"])
    if isinstance(manager, AsyncSharedCacheManager):
        view: SyncView[BsonDict] | AsyncView[BsonDict] = manager.get_cached_collection(
            manager.client[seeded_database]["catalogue"].with_options(**options)
        )
    else:
        view = manager.get_cached_collection(
            manager.client[seeded_database]["catalogue"].with_options(**options)
        )
    before = manager.snapshot()
    assert await _read(view, {"_id": 0}) is not None
    assert manager.snapshot().hits == before.hits
    assert manager.snapshot().bypasses == before.bypasses + 1
    assert manager.observation.bypasses[reason.value] == 1


async def test_default_identity_reads_refresh_collection_collation(
    manager: SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict],
    seeded_database: DatabaseName,
    client: MongoClient[BsonDict],
) -> None:
    await _warm(manager, manager[seeded_database]["catalogue"])
    raw = client[seeded_database].create_collection(
        "collated", collation=Collation("en", strength=2)
    )
    raw.insert_one({"_id": 0})
    view = manager[seeded_database][raw.name]
    before = manager.snapshot()
    for _ in range(2):
        assert await _read(view, {"_id": 0}) == {"_id": 0}
    assert manager.snapshot().hits == before.hits
    assert manager.snapshot().bypasses == before.bypasses + 2
    assert manager.observation.bypasses[adapters.PROTOTYPE_SCOPE] == 2


@pytest.mark.parametrize(
    "initial_owner_outage", ["crashed", "stalled", "control-lost"], indirect=True
)
async def test_new_workers_read_directly_and_recover_after_owner_outage(
    manager: SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict],
    server: SharedCacheServer,
    seeded_database: DatabaseName,
) -> None:
    view = manager[seeded_database]["catalogue"]
    assert manager.local is None
    started = time.monotonic()
    assert await _read(view, {"_id": 0}) is not None
    assert time.monotonic() - started < 2
    assert manager.snapshot().hits == 0
    server.restart()
    await _warm(manager, view)


async def test_public_find_bypasses_and_close_preserves_client(
    manager: SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict],
    seeded_database: DatabaseName,
) -> None:
    view = manager[seeded_database]["catalogue"]
    cursor = view.find({"_id": 0})
    if isinstance(cursor, AsyncCursor):
        assert len(await cursor.to_list()) == 1
    else:
        assert isinstance(cursor, Cursor)
        assert len(list(cursor)) == 1
    if isinstance(manager, AsyncSharedCacheManager):
        await manager.close()
        await manager.close()
        assert await manager.client.admin.command("ping")
    else:
        manager.close()
        manager.close()
        assert manager.client.admin.command("ping")
    with pytest.raises(CacheClosedError, match="closed"):
        await _read(view, {"_id": 0})


async def test_another_spawned_worker_uses_shared_values(
    manager: SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict],
    seeded_database: DatabaseName,
    request: pytest.FixtureRequest,
) -> None:
    view = manager[seeded_database]["catalogue"]
    await _warm(manager, view)
    pipe = request.getfixturevalue("spawned_worker")
    assert pipe.poll(10)
    document, hits = pipe.recv()
    assert document is not None
    assert hits == 1


async def test_silent_owner_stall_expires_hits(
    manager: SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict],
    seeded_database: DatabaseName,
    client: MongoClient[BsonDict],
    request: pytest.FixtureRequest,
) -> None:
    view = manager[seeded_database]["catalogue"]
    await _warm(manager, view)
    request.getfixturevalue("stopped_owner")
    client[seeded_database].catalogue.update_one(
        {"_id": 0}, {"$set": {"after_stall": True}}
    )
    await asyncio.sleep(3.1)
    document = await _read(view, {"_id": 0})
    assert document is not None
    assert document["after_stall"] is True


async def test_async_close_defers_repeated_cancellation(
    async_attached: AsyncSharedCacheManager[BsonDict], monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = async_attached
    entered, released = asyncio.Event(), asyncio.Event()
    original = AsyncLocalIndex.close

    async def delayed(local: AsyncLocalIndex) -> None:
        entered.set()
        await released.wait()
        await original(local)

    monkeypatch.setattr(AsyncLocalIndex, "close", delayed)
    task = asyncio.create_task(manager.close())
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    released.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert manager.local is not None
    assert manager.local.reader.detached
    await manager.close()


def test_private_endpoint_and_capability(server: SharedCacheServer) -> None:
    attachment = server.connection._attachment
    path = Path(attachment.socket_path)
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert attachment.capability.hex() not in repr(server.connection)
    assert repr(attachment.capability) not in repr(attachment)
    server.close()
    server.close()
    assert not path.parent.exists()
    with pytest.raises(CacheClosedError, match="closed"):
        server.restart()


def test_invalid_capability_does_not_break_other_workers(
    server: SharedCacheServer,
    client: MongoClient[BsonDict],
    rejected_connection: SharedCacheConnection,
) -> None:
    with pytest.raises(AttachmentConfigurationError):
        SharedCacheManager(client, rejected_connection)
    with SharedCacheManager(client, server.connection) as manager:
        assert manager.endpoint.connected


@pytest.fixture(params=({"capability": b"invalid"}, {"budget_bytes": 1}))
def rejected_connection(
    request: pytest.FixtureRequest, server: SharedCacheServer
) -> SharedCacheConnection:
    return replace(
        server.connection,
        _attachment=replace(server.connection._attachment, **request.param),
    )


@pytest.fixture(params=("request", "control"))
def manager_with_denied_endpoint(
    manager: SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict],
    unix_connect_fault: Callable[[PositiveInt, Callable[[], None]], None],
    request: pytest.FixtureRequest,
) -> SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict]:
    def deny() -> None:
        raise PermissionError(errno.EACCES, "access denied")

    unix_connect_fault(1 if request.param == "request" else 2, deny)
    return manager


async def test_persistent_attachment_access_failures_remain_visible(
    manager_with_denied_endpoint: SharedCacheManager[BsonDict]
    | AsyncSharedCacheManager[BsonDict],
    server: SharedCacheServer,
) -> None:
    manager = manager_with_denied_endpoint
    if isinstance(manager, AsyncSharedCacheManager):
        with pytest.raises(PermissionError, match="access denied"):
            await AsyncSharedCacheManager.attach(manager.client, server.connection)
    else:
        with pytest.raises(PermissionError, match="access denied"):
            SharedCacheManager(manager.client, server.connection)


@pytest.mark.parametrize(
    "value",
    [0, -1, True, 1.5, None],
    ids=("zero", "negative", "boolean", "float", "none"),
)
def test_configuration_rejects_invalid_limits(value: object) -> None:
    with pytest.raises(CacheConfigurationError, match="positive built-in"):
        SharedCacheConfig(slots=value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "module",
    ["client_query_cache.synchronous", "client_query_cache.asynchronous"],
    ids=("sync", "async"),
)
def test_public_module_attribute_errors(module: str) -> None:
    with pytest.raises(AttributeError):
        assert importlib.import_module(module).undefined is None


@pytest.mark.parametrize(
    "databases",
    [(), ("",), ("duplicate", "duplicate")],
    ids=("empty", "empty-name", "duplicate"),
)
def test_server_rejects_invalid_databases(databases: tuple[str, ...]) -> None:
    with pytest.raises(CacheConfigurationError, match="nonempty"):
        SharedCacheServer("mongodb://127.0.0.1:1", databases)


def test_configuration_rejects_an_entry_larger_than_arena() -> None:
    with pytest.raises(CacheConfigurationError, match="arena_bytes"):
        SharedCacheConfig(arena_bytes=1)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("slots", 3),
        ("slots", 1 << 63),
        ("arena_bytes", 1 << 35),
        ("namespaces", 1 << 32),
        ("connections", 1),
    ],
    ids=(
        "slot-power",
        "slot-overflow",
        "arena-overflow",
        "namespace-overflow",
        "no-worker-capacity",
    ),
)
def test_native_layout_limits_are_checked_before_allocation(
    field: str, value: PositiveInt
) -> None:
    with pytest.raises(CacheConfigurationError, match=field):
        replace(SharedCacheConfig(), **{field: value})


async def test_supported_hot_set_reuses_identity_encodings(  # noqa: RUF029 - Shared asyncio managers require a running event loop.
    manager: SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict],
    seeded_database: DatabaseName,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = manager[seeded_database]["catalogue"]
    first = tuple(
        adapters._identity_keys(view, identity, view._find_one_default_shape)
        for identity in range(4096)
    )
    encoder = Mock(wraps=wire.encode_key)
    monkeypatch.setattr(wire, "encode_key", encoder)
    second = tuple(
        adapters._identity_keys(view, identity, view._find_one_default_shape)
        for identity in range(4096)
    )
    assert second == first
    encoder.assert_not_called()


@pytest.mark.parametrize("worker_type_registry", [True], indirect=True)
async def test_custom_decoding_that_cannot_form_a_key_uses_the_driver(
    manager: SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict],
    seeded_database: DatabaseName,
) -> None:
    view = manager[seeded_database]["catalogue"]
    before = manager.snapshot()
    document = await _read(view, {"_id": 0})
    assert document is not None
    assert document["_id"] == {0}
    assert manager.snapshot().bypasses == before.bypasses + 1
    assert manager.snapshot().hits == before.hits


async def test_bson_timestamps_are_portable_shared_keys(
    manager: SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict],
    seeded_database: DatabaseName,
    faker: Faker,
) -> None:
    view = manager[seeded_database]["catalogue"]
    await _warm(manager, view)
    identity = Timestamp(faker.pyint(), faker.pyint())
    before = manager.snapshot()

    assert await _read(view, {"_id": identity}) is None

    assert manager.snapshot().hits == before.hits
    assert manager.snapshot().bypasses == before.bypasses
    assert manager.snapshot().misses == before.misses + 1


def test_server_rejects_unsupported_architecture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "machine", lambda: "unsupported")
    with pytest.raises(CacheConfigurationError, match="Linux x86-64"):
        SharedCacheServer("mongodb://127.0.0.1:1", ("application",))


def test_startup_failure_is_sanitized() -> None:
    with pytest.raises(CacheConfigurationError, match="startup reply"):
        SharedCacheServer("mongodb://[invalid", ("application",))


@pytest.mark.parametrize("restart", [False, True], ids=("initial", "restart"))
def test_aborted_owner_startup_releases_resources(
    restart: bool, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    action = (
        request.getfixturevalue("server").restart
        if restart
        else partial(SharedCacheServer, "mongodb://127.0.0.1:1", ("application",))
    )
    monkeypatch.setattr(shared, "_owner_main", _abrupt_owner)
    with pytest.raises(CacheConfigurationError, match="failed to start"):
        action()


def test_startup_timeout_reaps_the_child(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shared, "_owner_main", _stalled_startup)
    with pytest.raises(CacheConfigurationError, match="timed out"):
        SharedCacheServer("mongodb://127.0.0.1:1", ("application",))


@pytest.mark.parametrize("inherited", [True, False], ids=("inherited", "closed"))
def test_server_context_rejects_invalid_ownership(
    server: SharedCacheServer, monkeypatch: pytest.MonkeyPatch, inherited: bool
) -> None:
    if inherited:
        monkeypatch.setattr(server, "_pid", os.getpid() + 1)
    else:
        server.close()
    with pytest.raises(CacheClosedError):
        server.__enter__()
    if inherited:
        monkeypatch.setattr(server, "_pid", os.getpid())


def test_shutdown_reaps_a_stopped_owner(server: SharedCacheServer) -> None:
    assert server._process is not None
    pid = server._process.pid
    assert pid is not None
    os.kill(pid, signal.SIGSTOP)
    server.close()
    assert not psutil.pid_exists(pid)


async def test_parent_loss_stops_owner_and_removes_endpoint(
    abrupt_parent: Connection,
) -> None:
    assert abrupt_parent.poll(10)
    path, pid = abrupt_parent.recv()
    abrupt_parent.send("exit")
    deadline = time.monotonic() + 10
    owner = psutil.Process(pid)
    while Path(path).parent.exists() or (
        owner.is_running() and owner.status() != psutil.STATUS_ZOMBIE
    ):
        assert time.monotonic() < deadline
        await asyncio.sleep(0.02)


async def test_public_managers_reject_a_foreign_client(  # noqa: RUF029 - Async manager validation requires a running event loop.
    manager: SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict],
    client: MongoClient[BsonDict],
    async_client: AsyncMongoClient[BsonDict],
) -> None:
    operation = (
        partial(manager.get_cached_collection, async_client.application.items)
        if isinstance(manager, AsyncSharedCacheManager)
        else partial(manager.get_cached_collection, client.application.items)
    )
    with pytest.raises(ValueError, match="different client"):
        operation()


async def test_async_manager_requires_attachment(
    server: SharedCacheServer, async_client: AsyncMongoClient[BsonDict]
) -> None:
    manager = AsyncSharedCacheManager(async_client, server.connection)
    with pytest.raises(CacheClosedError, match="async context"):
        manager["application"]
    async with manager:
        assert await manager.__aenter__() is manager


async def test_async_attachment_failure_closes_manager(
    rejected_connection: SharedCacheConnection,
    async_client: AsyncMongoClient[BsonDict],
) -> None:
    manager = AsyncSharedCacheManager(async_client, rejected_connection)
    with pytest.raises(CacheConfigurationError):
        await manager.__aenter__()
    assert manager._closed


@pytest.mark.parametrize("server", [3], indirect=True)
def test_partial_attachment_failure_releases_endpoint(
    sync_attached: SharedCacheManager[BsonDict],
    server: SharedCacheServer,
    client: MongoClient[BsonDict],
) -> None:
    with SharedCacheManager(client, server.connection) as degraded:
        assert degraded.local is None
        assert degraded.endpoint.request({"op": "observe"}) is not None
    assert sync_attached.endpoint.request({"op": "observe"}) is not None


@pytest.fixture
def interrupted_control(
    sync_attached: SharedCacheManager[BsonDict],
    server: SharedCacheServer,
    unix_connect_fault: Callable[[PositiveInt, Callable[[], None]], None],
) -> SharedCacheConnection:
    assert sync_attached.endpoint.connected
    unix_connect_fault(2, partial(signal.raise_signal, signal.SIGINT))
    return server.connection


@pytest.mark.parametrize("server", [3], indirect=True)
def test_interrupted_control_handshake_releases_partial_request_connection(
    interrupted_control: SharedCacheConnection,
    client: MongoClient[BsonDict],
    sync_attached: SharedCacheManager[BsonDict],
) -> None:
    with pytest.raises(KeyboardInterrupt):
        SharedCacheManager(client, interrupted_control)

    def only_original_connections() -> bool:
        reply = sync_attached.endpoint.request({"op": "observe"})
        assert reply is not None
        return reply["connections"] == 2

    wait_for(only_original_connections)


@pytest.fixture
def foreign_loop() -> Iterator[asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


async def test_async_manager_rejects_another_event_loop(
    async_attached: AsyncSharedCacheManager[BsonDict],
    foreign_loop: asyncio.AbstractEventLoop,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(async_attached, "_loop", foreign_loop)
    with pytest.raises(CacheClosedError, match="event loop"):
        await async_attached.__aenter__()


class HandshakeGate(TypedDict):
    started: threading.Event
    release: threading.Event
    controls: list[ControlAttachment]


@pytest.fixture
def handshake_gate(monkeypatch: pytest.MonkeyPatch) -> Iterator[HandshakeGate]:
    gate: HandshakeGate = {
        "started": threading.Event(),
        "release": threading.Event(),
        "controls": [],
    }
    original = attachment.control_handshake

    def delayed(config: AttachmentConfig) -> ControlAttachment:
        control = original(config)
        gate["controls"].append(control)
        gate["started"].set()
        assert gate["release"].wait(5)
        return control

    monkeypatch.setattr(attachment, "control_handshake", delayed)
    yield gate
    gate["release"].set()
    for control in gate["controls"]:
        control.sock.close()


async def test_cancelled_handshake_closes_received_mapping_socket(
    server: SharedCacheServer, handshake_gate: HandshakeGate
) -> None:
    task = asyncio.create_task(AsyncLocalIndex.attach(server.connection._attachment))
    assert await asyncio.to_thread(handshake_gate["started"].wait, 5)
    task.cancel()
    handshake_gate["release"].set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert handshake_gate["controls"][0].sock.fileno() == -1


@pytest.fixture(
    params=(OSError("too many open files"), asyncio.CancelledError()),
    ids=("descriptor-limit", "cancelled"),
)
def failed_unix_connection(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> type[BaseException]:
    failure = request.param
    monkeypatch.setattr(asyncio, "open_unix_connection", AsyncMock(side_effect=failure))
    return type(failure)


async def test_failed_stream_open_closes_handshake_socket(
    server: SharedCacheServer,
    handshake_gate: HandshakeGate,
    failed_unix_connection: type[BaseException],
) -> None:
    handshake_gate["release"].set()
    with pytest.raises(failed_unix_connection):
        await AsyncLocalIndex.attach(server.connection._attachment)
    assert handshake_gate["controls"][0].sock.fileno() == -1
