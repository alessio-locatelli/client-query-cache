# Research prototype adapters around the supported facades; not a public API.
# ruff: noqa: SLF001
from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, override

from bson.errors import BSONError

from benchmarks.stream_cost.shared_cache.wire import UnportableKeyError, to_wire
from client_query_cache._core.canonical import canonicalize, is_canonicalizable
from client_query_cache._core.codec import codec_fingerprint, decode_value, encode_value
from client_query_cache._core.collection_metadata import CollectionMetadata
from client_query_cache._core.cursor_capture import CursorCapture
from client_query_cache._core.find_reads import find_read_shape
from client_query_cache._core.identity_reads import (
    NO_IDENTITY,
    extract_id_identity,
    normalize_identity_for_cache_key,
)
from client_query_cache._core.order_sensitive_keys import order_sensitive_key
from client_query_cache._core.read_classification import query_bypass_reason
from client_query_cache._core.snapshots import BypassReason
from client_query_cache._types import NonNegativeInt
from client_query_cache.asynchronous import collection as async_collection
from client_query_cache.asynchronous import cursors as async_cursors
from client_query_cache.asynchronous import database as async_database
from client_query_cache.synchronous import collection as sync_collection
from client_query_cache.synchronous import cursors as sync_cursors
from client_query_cache.synchronous import database as sync_database

if TYPE_CHECKING:
    from collections.abc import Callable

    from bson.codec_options import CodecOptions
    from pymongo import AsyncMongoClient, MongoClient
    from pymongo.asynchronous.collection import AsyncCollection
    from pymongo.asynchronous.database import AsyncDatabase
    from pymongo.synchronous.collection import Collection
    from pymongo.synchronous.database import Database

    from benchmarks.stream_cost.shared_cache.attachment import (
        AsyncEndpoint,
        Message,
        SyncEndpoint,
    )
    from client_query_cache._core.collection_metadata import CollectionProbeResult
    from client_query_cache._core.find_reads import FindReadShape, FindSource
    from client_query_cache._core.keys import NamespaceId

    type Shared = SharedCacheManager[Any] | AsyncSharedCacheManager[Any]
    type Cursor = SharedCachedCursor[Any] | AsyncSharedCachedCursor[Any]
    type View = SharedCachedCollection[Any] | AsyncSharedCachedCollection[Any]

_STALE = CollectionMetadata(checked_epoch=0, bypass_reason=None, default_collation=None)
UNPORTABLE_KEY = "unportable-key"
PROTOTYPE_SCOPE = "prototype-scope"
METADATA_REFRESH = "metadata-refresh"
OWNER_UNAVAILABLE = "owner-unavailable"


@dataclass(slots=True)
class LocalObservation:
    hits: NonNegativeInt = 0
    misses: NonNegativeInt = 0
    bypasses: dict[str, NonNegativeInt] = field(default_factory=dict)

    def record_bypass(self, reason: BypassReason | str) -> None:
        key = reason.value if isinstance(reason, BypassReason) else reason
        try:
            self.bypasses[key] += 1
        except KeyError:
            self.bypasses[key] = 1

    def record_oversized_bypass(self) -> None:
        self.record_bypass("oversized")


class _RemoteCaptureCore:
    __slots__ = ("_send", "max_entry_bytes", "observation")

    def __init__(
        self,
        send: Callable[[Message], None],
        max_entry_bytes: NonNegativeInt,
        observation: LocalObservation,
    ) -> None:
        self._send = send
        self.max_entry_bytes = max_entry_bytes
        self.observation = observation

    def snapshot(self) -> _RemoteCaptureCore:
        return self

    def record_oversized_bypass(self) -> None:
        self.observation.record_oversized_bypass()

    def discard(self, handle: object) -> None:
        self._send({"op": "discard", "handle": handle})

    def admit_namespace(
        self,
        capture: object,
        _discriminator: object,
        documents: object,
        *,
        codec_options: CodecOptions[Any],
        find_source: FindSource | None,  # noqa: ARG002 - The owner derives it.
    ) -> None:
        self._send(_admission(capture, documents, codec_options))


class RemoteCursorCapture(CursorCapture):
    __slots__ = ("_remote",)

    def __init__(
        self,
        remote: _RemoteCaptureCore,
        handle: object,
        discriminator: object,
        codec_options: CodecOptions[Any],
        *,
        find_source: FindSource | None,
    ) -> None:
        super().__init__(
            remote,  # type: ignore[arg-type]
            handle,  # type: ignore[arg-type]
            discriminator,
            codec_options,
            find_source=find_source,
        )
        self._remote = remote

    @override
    def abandon(self) -> None:
        if self._active:
            self._remote.discard(self._capture)
        super().abandon()


def _admission(
    handle: object, value: object, codec_options: CodecOptions[Any]
) -> Message:
    try:
        encoded = encode_value(value, codec_options)
    except BSONError:
        return {"op": "discard", "handle": handle}
    return {"op": "admit", "handle": handle, "value": encoded}


def _metadata(
    reply: Message | None, probe_result: CollectionProbeResult | None
) -> CollectionMetadata | BypassReason | str:
    if reply is None:
        return OWNER_UNAVAILABLE
    if reply["r"] != "ok":
        return str(reply["reason"])
    if probe_result is None:
        return BypassReason.METADATA_UNAVAILABLE
    if probe_result.bypass_reason in {
        BypassReason.MISSING_COLLECTION,
        BypassReason.METADATA_UNAVAILABLE,
    }:
        return probe_result.bypass_reason
    epoch = reply["epoch"]
    assert isinstance(epoch, int)
    return CollectionMetadata(
        checked_epoch=epoch,
        bypass_reason=probe_result.bypass_reason,
        default_collation=probe_result.default_collation,
    )


def _select(
    shared: Shared, operation: str, namespace: NamespaceId, **fields: object
) -> Message:
    return {
        "op": operation,
        "ns": [namespace.database, namespace.collection],
        "epoch": shared._metadata[namespace].checked_epoch,
        **fields,
    }


def _identity_message(
    view: View, identity: object, read_shape: object
) -> Message | str:
    cache_identity = normalize_identity_for_cache_key(
        identity, view._collection.codec_options, view._shared.client.codec_options
    )
    if not is_canonicalizable(cache_identity):
        return BypassReason.UNCANONICALIZABLE_KEY.value
    try:
        identity_key = to_wire(canonicalize(order_sensitive_key(cache_identity)))
        shape_key = to_wire(read_shape)
    except UnportableKeyError:
        return UNPORTABLE_KEY
    return _select(
        view._shared,
        "select-identity",
        view._namespace(),
        identity=identity_key,
        shape=shape_key,
    )


def _find_message(cursor: Cursor, shape: FindReadShape) -> Message | str:
    try:
        family = to_wire(canonicalize(shape.family))
    except UnportableKeyError:
        return UNPORTABLE_KEY
    return _select(
        cursor._shared,
        "select-find",
        cursor._view._namespace(),
        family=family,
        limit=shape.limit,
    )


def _find_reason(cursor: Cursor, shape: FindReadShape) -> BypassReason | None:
    unsupported = (
        cursor._unsupported
        or cursor._query_flags
        or cursor._explain
        or any(
            option is not None
            for option in (
                cursor._hint,
                cursor._comment,
                cursor._max_time_ms,
                cursor._max_await_time_ms,
                cursor._max_scan,
                cursor._max,
                cursor._min,
                cursor._return_key,
                cursor._show_record_id,
                cursor._snapshot,
                cursor._allow_disk_use,
                cursor._let,
            )
        )
    )
    return cursor._view._request_bypass_reason(
        session=cursor._session,  # type: ignore[arg-type]
        kwargs={"cursor_options": True} if unsupported else {},
    ) or query_bypass_reason(cursor._spec, cursor._projection, shape.discriminator)


def _shape(cursor: Cursor) -> FindReadShape:
    return find_read_shape(
        cursor._spec,
        cursor._projection,
        cursor._ordering,
        cursor._skip,
        cursor._limit,
        collation=cursor._collation,
        codec=codec_fingerprint(cursor._codec_options),
    )


def _outcome(shared: Shared, namespace: NamespaceId, reply: Message | None) -> str:
    if reply is None:
        shared.observation.record_bypass(OWNER_UNAVAILABLE)
        return "bypass"
    kind = str(reply["r"])
    if kind == "refresh":
        shared._metadata[namespace] = _STALE
        shared.observation.record_bypass(METADATA_REFRESH)
    elif kind == "bypass":
        shared.observation.record_bypass(str(reply["reason"]))
    elif kind == "hit":
        shared.observation.hits += 1
    else:
        shared.observation.misses += 1
    return kind


def _apply_find_reply(
    cursor: Cursor, reply: Message | None, shape: FindReadShape
) -> None:
    shared = cursor._shared
    outcome = _outcome(shared, cursor._view._namespace(), reply)
    if outcome == "hit":
        assert reply is not None
        documents: list[Any] = decode_value(  # type: ignore[assignment]
            reply["value"],  # type: ignore[arg-type]
            cursor._codec_options,
        )
        if shape.limit > 0:
            documents = documents[: shape.limit]
        cursor._data = deque(documents)
        cursor._retrieved = len(documents)
        cursor._id = 0
        cursor._killed = True
        return
    if outcome != "miss":
        return
    assert reply is not None
    if reply["handle"] is None:
        return
    cursor._capture = RemoteCursorCapture(
        _RemoteCaptureCore(
            shared.endpoint.send, shared.max_entry_bytes, shared.observation
        ),
        reply["handle"],
        shape.discriminator,
        cursor._codec_options,
        find_source=shape.source,
    )
    forced = cursor._view._forced_collection_handle()
    cursor._read_concern = forced.read_concern
    cursor._read_preference = forced.read_preference


def _identity_outcome(
    view: View, message: Message | str, reply: Message | None
) -> tuple[str, object]:
    if isinstance(message, str):
        view._shared.observation.record_bypass(message)
        return "bypass", None
    outcome = _outcome(view._shared, view._namespace(), reply)
    if outcome == "hit":
        assert reply is not None
        return outcome, decode_value(
            reply["value"],  # type: ignore[arg-type]
            view._collection.codec_options,
        )
    if outcome == "miss":
        assert reply is not None
        return outcome, reply["handle"]
    return outcome, None


def _prototype_scope(view: View, filter_query: object) -> bool:
    if extract_id_identity(filter_query) is not NO_IDENTITY and (
        view._shared._default_collation_for(view._namespace()) is None
    ):
        return False
    view._shared.observation.record_bypass(PROTOTYPE_SCOPE)
    return True


class SharedCachedCursor[DocumentType: Mapping[str, Any]](
    sync_cursors.CachedCursor[DocumentType]
):
    def __init__(
        self,
        view: SharedCachedCollection[DocumentType],
        *args: object,
        **kwargs: object,
    ) -> None:
        self._shared: SharedCacheManager[Any] = view._shared
        super().__init__(view, *args, **kwargs)

    @override
    def _prepare(self) -> None:
        self._prepared = True
        shape = _shape(self)
        reason = _find_reason(self, shape) or self._view._cache_ineligibility_reason()
        if reason is not None:
            self._shared.observation.record_bypass(reason)
            return
        message = _find_message(self, shape)
        if isinstance(message, str):
            self._shared.observation.record_bypass(message)
            return
        _apply_find_reply(self, self._shared.endpoint.request(message), shape)

    @override
    def _clone_base(self, session: Any) -> SharedCachedCursor[DocumentType]:
        view = self._view
        assert isinstance(view, SharedCachedCollection)
        clone = SharedCachedCursor(view, session=session)
        clone._unsupported = self._unsupported
        return clone


class AsyncSharedCachedCursor[DocumentType: Mapping[str, Any]](
    async_cursors.CachedCursor[DocumentType]
):
    def __init__(
        self,
        view: AsyncSharedCachedCollection[DocumentType],
        *args: object,
        **kwargs: object,
    ) -> None:
        self._shared: AsyncSharedCacheManager[Any] = view._shared
        super().__init__(view, *args, **kwargs)

    @override
    async def _prepare(self) -> None:
        self._prepared = True
        shape = _shape(self)
        reason = (
            _find_reason(self, shape) or await self._view._cache_ineligibility_reason()
        )
        if reason is not None:
            self._shared.observation.record_bypass(reason)
            return
        message = _find_message(self, shape)
        if isinstance(message, str):
            self._shared.observation.record_bypass(message)
            return
        _apply_find_reply(self, await self._shared.endpoint.request(message), shape)

    @override
    def _clone_base(self, session: Any) -> AsyncSharedCachedCursor[DocumentType]:
        view = self._view
        assert isinstance(view, AsyncSharedCachedCollection)
        clone = AsyncSharedCachedCursor(view, session=session)
        clone._unsupported = self._unsupported
        return clone


class SharedCachedCollection[DocumentType: Mapping[str, Any]](
    sync_collection.CachedCollection[DocumentType]
):
    __slots__ = ("_shared",)

    def __init__(
        self,
        database: SharedCachedDatabase[DocumentType],
        collection: Collection[DocumentType],
    ) -> None:
        super().__init__(database, collection)
        self._shared: SharedCacheManager[DocumentType] = database.shared

    @override
    def __getitem__(self, name: str) -> SharedCachedCollection[DocumentType]:
        database = self._database
        assert isinstance(database, SharedCachedDatabase)
        return SharedCachedCollection(database, self._collection[name])

    @override
    def find_one(
        self,
        filter: object = None,
        projection: Mapping[str, Any] | Sequence[str] | None = None,
        **kwargs: Any,
    ) -> DocumentType | None:
        if _prototype_scope(self, filter):
            return self._collection.find_one(filter, projection, **kwargs)
        return super().find_one(filter, projection, **kwargs)

    @override
    def find(self, *args: object, **kwargs: object) -> SharedCachedCursor[DocumentType]:
        return SharedCachedCursor(self, *args, **kwargs)

    @override
    def _find_one_by_id(
        self,
        identity: object,
        projection: Mapping[str, Any] | Sequence[str] | None,
        read_shape: object,
        *,
        sort: Sequence[tuple[str, int]] | None,
        collation: Any,
    ) -> DocumentType | None:
        message = _identity_message(self, identity, read_shape)
        endpoint = self._shared.endpoint
        reply = endpoint.request(message) if isinstance(message, dict) else None
        outcome, value = _identity_outcome(self, message, reply)
        if outcome == "hit":
            return value  # type: ignore[return-value]
        if outcome != "miss":
            return self._collection.find_one(
                {"_id": identity}, projection, sort=sort, collation=collation
            )
        try:
            document = self._forced_collection_handle().find_one(
                {"_id": identity}, projection, sort=sort, collation=collation
            )
        except BaseException:
            if value is not None:
                endpoint.send({"op": "discard", "handle": value})
            raise
        if value is not None:
            endpoint.send(_admission(value, document, self._collection.codec_options))
        return document

    @override
    def aggregate(self, *args: Any, **kwargs: Any) -> Any:
        self._shared.observation.record_bypass(PROTOTYPE_SCOPE)
        return self._collection.aggregate(*args, **kwargs)

    @override
    def count_documents(self, *args: Any, **kwargs: Any) -> Any:
        self._shared.observation.record_bypass(PROTOTYPE_SCOPE)
        return self._collection.count_documents(*args, **kwargs)

    @override
    def estimated_document_count(self, **kwargs: Any) -> Any:
        self._shared.observation.record_bypass(PROTOTYPE_SCOPE)
        return self._collection.estimated_document_count(**kwargs)

    @override
    def distinct(self, *args: Any, **kwargs: Any) -> Any:
        self._shared.observation.record_bypass(PROTOTYPE_SCOPE)
        return self._collection.distinct(*args, **kwargs)


class AsyncSharedCachedCollection[DocumentType: Mapping[str, Any]](
    async_collection.CachedCollection[DocumentType]
):
    __slots__ = ("_shared",)

    def __init__(
        self,
        database: AsyncSharedCachedDatabase[DocumentType],
        collection: AsyncCollection[DocumentType],
    ) -> None:
        super().__init__(database, collection)
        self._shared: AsyncSharedCacheManager[DocumentType] = database.shared

    @override
    def __getitem__(self, name: str) -> AsyncSharedCachedCollection[DocumentType]:
        database = self._database
        assert isinstance(database, AsyncSharedCachedDatabase)
        return AsyncSharedCachedCollection(database, self._collection[name])

    @override
    async def find_one(
        self,
        filter: object = None,
        projection: Mapping[str, Any] | Sequence[str] | None = None,
        **kwargs: Any,
    ) -> DocumentType | None:
        if _prototype_scope(self, filter):
            return await self._collection.find_one(filter, projection, **kwargs)
        return await super().find_one(filter, projection, **kwargs)

    @override
    def find(
        self, *args: object, **kwargs: object
    ) -> AsyncSharedCachedCursor[DocumentType]:
        return AsyncSharedCachedCursor(self, *args, **kwargs)

    @override
    async def _find_one_by_id(
        self,
        identity: object,
        projection: Mapping[str, Any] | Sequence[str] | None,
        read_shape: object,
        *,
        sort: Sequence[tuple[str, int]] | None,
        collation: Any,
    ) -> DocumentType | None:
        message = _identity_message(self, identity, read_shape)
        endpoint = self._shared.endpoint
        reply = await endpoint.request(message) if isinstance(message, dict) else None
        outcome, value = _identity_outcome(self, message, reply)
        if outcome == "hit":
            return value  # type: ignore[return-value]
        if outcome != "miss":
            return await self._collection.find_one(
                {"_id": identity}, projection, sort=sort, collation=collation
            )
        try:
            document = await self._forced_collection_handle().find_one(
                {"_id": identity}, projection, sort=sort, collation=collation
            )
        except BaseException:
            if value is not None:
                endpoint.send({"op": "discard", "handle": value})
            raise
        if value is not None:
            endpoint.send(_admission(value, document, self._collection.codec_options))
        return document

    @override
    async def aggregate(self, *args: Any, **kwargs: Any) -> Any:
        self._shared.observation.record_bypass(PROTOTYPE_SCOPE)
        return await self._collection.aggregate(*args, **kwargs)

    @override
    async def count_documents(self, *args: Any, **kwargs: Any) -> Any:
        self._shared.observation.record_bypass(PROTOTYPE_SCOPE)
        return await self._collection.count_documents(*args, **kwargs)

    @override
    async def estimated_document_count(self, **kwargs: Any) -> Any:
        self._shared.observation.record_bypass(PROTOTYPE_SCOPE)
        return await self._collection.estimated_document_count(**kwargs)

    @override
    async def distinct(self, *args: Any, **kwargs: Any) -> Any:
        self._shared.observation.record_bypass(PROTOTYPE_SCOPE)
        return await self._collection.distinct(*args, **kwargs)


class SharedCachedDatabase[DocumentType: Mapping[str, Any]](
    sync_database.CachedDatabase[DocumentType]
):
    __slots__ = ("shared",)

    def __init__(
        self,
        manager: SharedCacheManager[DocumentType],
        database: Database[DocumentType],
    ) -> None:
        super().__init__(manager, database)  # type: ignore[arg-type]
        self.shared = manager

    @override
    def __getitem__(self, name: str) -> SharedCachedCollection[DocumentType]:
        return SharedCachedCollection(self, self._database[name])


class AsyncSharedCachedDatabase[DocumentType: Mapping[str, Any]](
    async_database.CachedDatabase[DocumentType]
):
    __slots__ = ("shared",)

    def __init__(
        self,
        manager: AsyncSharedCacheManager[DocumentType],
        database: AsyncDatabase[DocumentType],
    ) -> None:
        super().__init__(manager, database)  # type: ignore[arg-type]
        self.shared = manager

    @override
    def __getitem__(self, name: str) -> AsyncSharedCachedCollection[DocumentType]:
        return AsyncSharedCachedCollection(self, self._database[name])


class SharedCacheManager[DocumentType: Mapping[str, Any]]:
    __slots__ = ("_client", "_metadata", "endpoint", "max_entry_bytes", "observation")

    def __init__(
        self, client: MongoClient[DocumentType], endpoint: SyncEndpoint
    ) -> None:
        self._client = client
        self.endpoint = endpoint
        self.max_entry_bytes = endpoint.config.max_entry_bytes
        self.observation = LocalObservation()
        self._metadata: dict[NamespaceId, CollectionMetadata] = {}

    @property
    def client(self) -> MongoClient[DocumentType]:
        return self._client

    @property
    def cache_core(self) -> LocalObservation:
        return self.observation

    def _cache_ineligibility_reason(
        self,
        namespace: NamespaceId,
        probe: Callable[[], CollectionProbeResult | None],
    ) -> BypassReason | str | None:
        try:
            cached = self._metadata[namespace]
        except KeyError:
            cached = _STALE
        if cached is not _STALE:
            return cached.bypass_reason
        reply = self.endpoint.request(
            {"op": "metadata", "ns": [namespace.database, namespace.collection]}
        )
        metadata = _metadata(
            reply, probe() if reply is not None and reply["r"] == "ok" else None
        )
        if not isinstance(metadata, CollectionMetadata):
            return metadata
        self._metadata[namespace] = metadata
        return metadata.bypass_reason

    def _default_collation_for(
        self, namespace: NamespaceId
    ) -> Mapping[str, Any] | None:
        try:
            return self._metadata[namespace].default_collation
        except KeyError:
            return None

    def __getitem__(self, name: str) -> SharedCachedDatabase[DocumentType]:
        return SharedCachedDatabase(self, self._client[name])

    def get_cached_collection(
        self, collection: Collection[DocumentType]
    ) -> SharedCachedCollection[DocumentType]:
        if collection.database.client is not self._client:
            message = "collection belongs to a different client"
            raise ValueError(message)
        return SharedCachedCollection(
            SharedCachedDatabase(self, collection.database), collection
        )

    def close(self) -> None:
        self.endpoint.close()


class AsyncSharedCacheManager[DocumentType: Mapping[str, Any]]:
    __slots__ = ("_client", "_metadata", "endpoint", "max_entry_bytes", "observation")

    def __init__(
        self, client: AsyncMongoClient[DocumentType], endpoint: AsyncEndpoint
    ) -> None:
        self._client = client
        self.endpoint = endpoint
        self.max_entry_bytes = endpoint.config.max_entry_bytes
        self.observation = LocalObservation()
        self._metadata: dict[NamespaceId, CollectionMetadata] = {}

    @property
    def client(self) -> AsyncMongoClient[DocumentType]:
        return self._client

    @property
    def cache_core(self) -> LocalObservation:
        return self.observation

    async def _cache_ineligibility_reason(
        self,
        namespace: NamespaceId,
        probe: Callable[[], Any],
    ) -> BypassReason | str | None:
        try:
            cached = self._metadata[namespace]
        except KeyError:
            cached = _STALE
        if cached is not _STALE:
            return cached.bypass_reason
        reply = await self.endpoint.request(
            {"op": "metadata", "ns": [namespace.database, namespace.collection]}
        )
        metadata = _metadata(
            reply, await probe() if reply is not None and reply["r"] == "ok" else None
        )
        if not isinstance(metadata, CollectionMetadata):
            return metadata
        self._metadata[namespace] = metadata
        return metadata.bypass_reason

    def _default_collation_for(
        self, namespace: NamespaceId
    ) -> Mapping[str, Any] | None:
        try:
            return self._metadata[namespace].default_collation
        except KeyError:
            return None

    def __getitem__(self, name: str) -> AsyncSharedCachedDatabase[DocumentType]:
        return AsyncSharedCachedDatabase(self, self._client[name])

    def get_cached_collection(
        self, collection: AsyncCollection[DocumentType]
    ) -> AsyncSharedCachedCollection[DocumentType]:
        if collection.database.client is not self._client:
            message = "collection belongs to a different client"
            raise ValueError(message)
        return AsyncSharedCachedCollection(
            AsyncSharedCachedDatabase(self, collection.database), collection
        )

    async def close(self) -> None:
        await self.endpoint.close()
