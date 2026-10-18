from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, override

from pymongo.collation import Collation

from client_query_cache._core.canonical import canonicalize
from client_query_cache._core.codec import decode_value, encode_value
from client_query_cache._core.collection_metadata import CollectionMetadata
from client_query_cache._core.count_reads import count_read_options
from client_query_cache._core.cursor_capture import CursorCapture
from client_query_cache._core.errors import CacheClosedError
from client_query_cache._core.find_one_reads import (
    CollationInput,
    find_one_options_cacheable,
    normalize_find_one_filter,
)
from client_query_cache._core.find_reads import FindReadShape, find_read_shape
from client_query_cache._core.identity_reads import (
    NO_IDENTITY,
    extract_id_anchor,
    normalize_identity_for_cache_key,
)
from client_query_cache._core.namespace_metadata import NamespaceMetadataCache
from client_query_cache._core.order_sensitive_keys import (
    order_sensitive_discriminator_key,
    order_sensitive_key,
)
from client_query_cache._core.read_classification import (
    _prepare_key,
    prepare_pipeline_key,
    prepare_query_key,
)
from client_query_cache._core.snapshots import BypassReason
from client_query_cache._shared.attachment import (
    AsyncLocalIndex,
    LocalIndex,
    attachment_unavailable,
)
from client_query_cache._shared.wire import (
    KeyCache,
    ProtocolError,
    UnportableKeyError,
)
from client_query_cache._types import NonNegativeInt, PositiveFloat
from client_query_cache.asynchronous import collection as async_collection
from client_query_cache.asynchronous import cursors as async_cursors
from client_query_cache.asynchronous import database as async_database
from client_query_cache.synchronous import collection as sync_collection
from client_query_cache.synchronous import cursors as sync_cursors
from client_query_cache.synchronous import database as sync_database

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from bson.codec_options import CodecOptions
    from pymongo import AsyncMongoClient, MongoClient
    from pymongo.asynchronous.client_session import AsyncClientSession
    from pymongo.asynchronous.collection import AsyncCollection
    from pymongo.asynchronous.command_cursor import AsyncCommandCursor
    from pymongo.asynchronous.database import AsyncDatabase
    from pymongo.client_session import ClientSession
    from pymongo.synchronous.collection import Collection
    from pymongo.synchronous.command_cursor import CommandCursor
    from pymongo.synchronous.database import Database

    from client_query_cache._core.canonical import Canonical
    from client_query_cache._core.collection_metadata import CollectionProbeResult
    from client_query_cache._core.find_reads import FindSource
    from client_query_cache._core.keys import NamespaceId
    from client_query_cache._shared.attachment import (
        AsyncEndpoint,
        Message,
        SyncEndpoint,
    )
    from client_query_cache._shared_index import ReaderIndex

    type Shared = SharedCacheManager[Any] | AsyncSharedCacheManager[Any]
    type Cursor = SharedCachedCursor[Any] | AsyncSharedCachedCursor[Any]
    type View = SharedCachedCollection[Any] | AsyncSharedCachedCollection[Any]

_STALE = CollectionMetadata(checked_epoch=0, bypass_reason=None, default_collation=None)
UNPORTABLE_KEY = "unportable-key"
PROTOTYPE_SCOPE = "shared-scope"
METADATA_REFRESH = "metadata-refresh"
OWNER_UNAVAILABLE = "owner-unavailable"
NO_LOCAL_HIT = object()
_KEY_CACHE_ENTRIES = 8192
_REATTACH_SECONDS = 0.1
_NEGATIVE_METADATA_TTL_SECONDS: PositiveFloat = 1.0


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


@dataclass(frozen=True, slots=True)
class SharedCacheStatistics:
    """Read counts for this worker attachment."""

    hits: NonNegativeInt
    misses: NonNegativeInt
    bypasses: NonNegativeInt


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
        admission = _admission(
            capture,
            documents,
            codec_options,
            self.max_entry_bytes,
            self.observation,
        )
        assert admission is not None
        self._send(admission)


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


@dataclass(frozen=True, slots=True)
class LocalMiss:
    message: Message
    reader: ReaderIndex


def _admission(
    handle: object,
    value: object,
    codec_options: CodecOptions[Any],
    max_entry_bytes: NonNegativeInt,
    observation: LocalObservation,
) -> Message | None:
    encoded = encode_value(value, codec_options)
    if len(encoded) > max_entry_bytes:
        observation.record_oversized_bypass()
        if isinstance(handle, LocalMiss):
            return None
        return {"op": "discard", "handle": handle}
    if isinstance(handle, LocalMiss):
        return {**handle.message, "value": encoded}
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


def _metadata_probe_token(reply: Message) -> NonNegativeInt:
    token = reply["probe_token"]
    if type(token) is not int or token < 0:
        raise ProtocolError("metadata probe token is invalid")
    return token


def _cached_metadata(
    metadata_cache: NamespaceMetadataCache[CollectionMetadata], namespace: NamespaceId
) -> CollectionMetadata | None:
    metadata = metadata_cache.find(namespace)
    if (
        metadata is not None
        and metadata.expires_at is not None
        and metadata.expires_at <= time.monotonic()
    ):
        metadata_cache.remove(namespace)
        return None
    return metadata


def _select(
    shared: Shared, operation: str, namespace: NamespaceId, **fields: object
) -> Message | str:
    metadata = _cached_metadata(shared._metadata, namespace)
    if metadata is None:
        return METADATA_REFRESH
    return {
        "op": operation,
        "ns": [namespace.database, namespace.collection],
        "epoch": metadata.checked_epoch,
        **fields,
    }


def _identity_keys(
    view: View, identity: object, read_shape: object
) -> tuple[bytes, bytes] | str:
    cache_identity = normalize_identity_for_cache_key(
        identity, view._collection.codec_options, view._shared.client.codec_options
    )
    default_shape = (
        view._default_shape_key if read_shape is view._find_one_default_shape else None
    )
    if isinstance(default_shape, str):
        return default_shape
    try:
        return (
            view._shared.keys.encode(canonicalize(order_sensitive_key(cache_identity))),
            default_shape
            if default_shape is not None
            else view._shared.keys.encode(read_shape),
        )
    except UnportableKeyError:
        return UNPORTABLE_KEY


def _default_shape_key(view: View) -> bytes | str:
    shape, reason = _prepare_key(view._find_one_default_shape)
    if reason is not None:
        return UNPORTABLE_KEY
    try:
        return view._shared.keys.encode(shape)
    except UnportableKeyError:
        return UNPORTABLE_KEY


def _identity_message(view: View, keys: tuple[bytes, bytes] | str) -> Message | str:
    if isinstance(keys, str):
        return keys
    identity_key, shape_key = keys
    return _select(
        view._shared,
        "select-identity",
        view._namespace(),
        identity=identity_key,
        shape=shape_key,
    )


def _local_select(view: View, keys: tuple[bytes, bytes] | str) -> object:
    shared = view._shared
    local = shared.local
    if local is None or isinstance(keys, str):
        return NO_LOCAL_HIT
    namespace = view._namespace()
    assignment = shared._slots.find(namespace)
    if assignment is None:
        return NO_LOCAL_HIT
    database, slot, incarnation = assignment
    if incarnation != local.incarnation:
        shared._reattach = True
        return NO_LOCAL_HIT
    metadata = _cached_metadata(shared._metadata, namespace)
    if metadata is None:
        return NO_LOCAL_HIT
    identity_key, shape_key = keys
    payload = local.reader.lookup(
        database, slot, metadata.checked_epoch, identity_key, shape_key
    )
    if payload is None:
        if local.reader.detached:
            shared._reattach = True
            return NO_LOCAL_HIT
        if identity_key == b"":
            return NO_LOCAL_HIT
        if (
            not local.admissions_enabled
            or shared.endpoint.counters.native_admission_recoveries
        ) and not shared.endpoint.connected:
            return NO_LOCAL_HIT
        token = local.reader.capture(database, slot, metadata.checked_epoch)
        if token is not None:
            shared.observation.misses += 1
            return LocalMiss(
                {
                    "op": "admit-local",
                    "ns": [namespace.database, namespace.collection],
                    "slot": [database, slot],
                    "epoch": metadata.checked_epoch,
                    "incarnation": incarnation,
                    "identity": identity_key,
                    "shape": shape_key,
                    "token": list(token),
                },
                local.reader,
            )
        return NO_LOCAL_HIT
    shared.observation.hits += 1
    return decode_value(payload, view._collection.codec_options)


def _remember_slot(shared: Shared, namespace: NamespaceId, reply: Message) -> None:
    try:
        slot = reply["slot"]
    except KeyError:
        return
    assert isinstance(slot, list)
    shared._slots.store(namespace, (slot[0], slot[1], shared.endpoint.incarnation))


def _reattached(shared: Shared) -> None:
    shared._reattach = False
    shared._slots.clear()
    shared._metadata.clear()


def _find_message(cursor: Cursor, shape: FindReadShape) -> Message | str:
    try:
        family = cursor._shared.keys.encode(canonicalize(shape.family))
    except UnportableKeyError:
        return UNPORTABLE_KEY
    return _select(
        cursor._shared,
        "select-find",
        cursor._view._namespace(),
        family=family,
        limit=shape.limit,
    )


def _local_find(cursor: Cursor, shape: FindReadShape) -> bool:
    if cursor._shared.local is None:
        return False
    try:
        key = cursor._shared.keys.encode(canonicalize(shape.discriminator))
    except UnportableKeyError:
        return False
    documents = _local_select(cursor._view, (b"", key))
    if documents is NO_LOCAL_HIT:
        return False
    assert isinstance(documents, list)
    _apply_find_hit(cursor, documents, shape.limit)
    return True


def _prepare_find_shape(
    cursor: Cursor, shape: FindReadShape
) -> tuple[FindReadShape, BypassReason | str | None]:
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
    reason: BypassReason | str | None = cursor._view._request_bypass_reason(
        session=cursor._session,  # type: ignore[arg-type]
        kwargs={"cursor_options": True} if unsupported else {},
    )
    reason = reason or _shared_collation_reason(cursor._collation)
    if reason is not None:
        return shape, reason
    family, reason = prepare_query_key(cursor._spec, cursor._projection, shape.family)
    return FindReadShape(family, shape.limit), reason


def _shape(cursor: Cursor) -> FindReadShape:
    return find_read_shape(
        cursor._spec,
        cursor._projection,
        cursor._ordering,
        cursor._skip,
        cursor._limit,
        collation=cursor._collation,
        codec=cursor._view._codec_identity,
    )


def _outcome(shared: Shared, namespace: NamespaceId, reply: Message | None) -> str:
    if reply is None:
        shared.observation.record_bypass(OWNER_UNAVAILABLE)
        return "bypass"
    kind = str(reply["r"])
    if kind == "refresh":
        shared._metadata.store(namespace, _STALE)
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
        _apply_find_hit(cursor, documents, shape.limit)
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
        canonicalize(shape.discriminator),
        cursor._codec_options,
        find_source=shape.source,
    )
    forced = cursor._view._forced_collection_handle()
    cursor._read_concern = forced.read_concern
    cursor._read_preference = forced.read_preference


def _apply_find_hit(cursor: Cursor, documents: list[Any], limit: int) -> None:
    if limit > 0 and len(documents) > limit:
        documents = documents[:limit]
    cursor._data = deque(documents)
    cursor._retrieved = len(documents)
    cursor._id = 0
    cursor._killed = True


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


def _shared_collation_reason(collation: object) -> str | None:
    if collation is None or (
        collation.document if isinstance(collation, Collation) else collation
    ) == {"locale": "simple"}:
        return None
    return PROTOTYPE_SCOPE


def _namespace_message(view: View, discriminator: object) -> Message | str:
    try:
        key = view._shared.keys.encode(canonicalize(discriminator))
    except UnportableKeyError:
        return UNPORTABLE_KEY
    return _select(view._shared, "select-namespace", view._namespace(), shape=key)


def _namespace_local(view: View, message: Message | str) -> object:
    if isinstance(message, str):
        return NO_LOCAL_HIT
    return _local_select(view, (b"", message["shape"]))  # type: ignore[arg-type]


def _remote_capture(
    view: View, handle: object, discriminator: object
) -> RemoteCursorCapture:
    return RemoteCursorCapture(
        _RemoteCaptureCore(
            view._shared.endpoint.send,
            view._shared.max_entry_bytes,
            view._shared.observation,
        ),
        handle,
        discriminator,
        view.raw.codec_options,
        find_source=None,
    )


def _scalar_key(
    view: View,
    method: str,
    filter_query: Mapping[str, Any] | None,
    projection: Mapping[str, Any] | Sequence[str] | None,
    collation: object,
    *,
    options: object,
    reason: BypassReason | str | None = None,
) -> tuple[object, BypassReason | str | None]:
    reason = reason or _shared_collation_reason(collation)
    if reason is not None:
        return None, reason
    discriminator = order_sensitive_discriminator_key(
        (
            method,
            filter_query,
            projection,
            (collation.document if isinstance(collation, Collation) else collation),
            options,
            view._codec_identity,
        )
    )
    discriminator, reason = prepare_query_key(filter_query, projection, discriminator)
    return discriminator, reason


def _count_key(
    view: View,
    filter_query: Mapping[str, Any],
    options: tuple[object, object, object, object],
    *,
    reason: BypassReason | str | None = None,
) -> tuple[object, BypassReason | str | None]:
    reason = reason or _shared_collation_reason(options[2])
    if reason is not None:
        return None, reason
    discriminator = order_sensitive_discriminator_key(
        (
            "count_documents",
            filter_query,
            *options,
            view._codec_identity,
        )
    )
    discriminator, reason = prepare_query_key(filter_query, None, discriminator)
    return discriminator, reason


def _publish_scalar(view: View, handle: object, value: object) -> None:
    if handle is None:
        return
    admission = _admission(
        handle,
        value,
        view.raw.codec_options,
        view._shared.max_entry_bytes,
        view._shared.observation,
    )
    assert admission is not None
    view._shared.endpoint.send(admission)


def _default_identity_request(
    view: View,
    filter_query: object,
    projection: object,
    collation: CollationInput | None,
    kwargs: Mapping[str, object],
) -> tuple[Mapping[str, Any], int, Canonical, BypassReason | None] | None:
    if (
        projection is not None
        or collation is not None
        or kwargs
        or type(filter_query) is not dict
        or len(filter_query) != 1
    ):
        return None
    if type(next(iter(filter_query))) is not str:
        return None
    try:
        identity = filter_query["_id"]
    except KeyError:
        return None
    if (
        type(identity) is not int
        or view._shared._default_collation_for(view._namespace()) is not None
    ):
        return None
    reason = view._request_bypass_reason(session=None, kwargs=kwargs)
    if reason is not None:
        return filter_query, identity, None, reason
    shape, reason = _prepare_key(view._find_one_default_shape)
    return filter_query, identity, shape, reason


class SharedCachedCursor[DocumentType: Mapping[str, Any]](
    sync_cursors.CachedCursor[DocumentType]
):
    _view: SharedCachedCollection[DocumentType]

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
        shape, reason = _prepare_find_shape(self, _shape(self))
        if reason is None:
            reason = self._view._cache_ineligibility_reason()
        if reason is not None:
            self._shared.observation.record_bypass(reason)
            return
        if _local_find(self, shape):
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
    _view: AsyncSharedCachedCollection[DocumentType]

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
        shape, reason = _prepare_find_shape(self, _shape(self))
        if reason is None:
            reason = await self._view._cache_ineligibility_reason()
        if reason is not None:
            self._shared.observation.record_bypass(reason)
            return
        if _local_find(self, shape):
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
    __slots__ = ("_default_shape_key", "_shared")

    def __init__(
        self,
        database: SharedCachedDatabase[DocumentType],
        collection: Collection[DocumentType],
    ) -> None:
        super().__init__(database, collection)
        self._shared: SharedCacheManager[DocumentType] = database.shared
        self._default_shape_key = _default_shape_key(self)

    def _read_namespace[Value](
        self,
        discriminator: object,
        reason: BypassReason | str | None,
        read: Callable[[Collection[DocumentType]], Value],
    ) -> Value:
        self._shared._check_open()
        if reason is None:
            reason = self._cache_ineligibility_reason()
        if reason is not None:
            self._shared.observation.record_bypass(reason)
            return read(self.raw)
        message = _namespace_message(self, discriminator)
        snapshot = _namespace_local(self, message)
        if snapshot is not NO_LOCAL_HIT:
            return snapshot  # type: ignore[return-value]
        reply = (
            self._shared.endpoint.request(message)
            if isinstance(message, dict)
            else None
        )
        outcome, handle = _identity_outcome(self, message, reply)
        if outcome == "hit":
            return handle  # type: ignore[return-value]
        if outcome != "miss":
            return read(self.raw)
        try:
            value = read(self._forced_collection_handle())
        except BaseException:
            if handle is not None:
                self._shared.endpoint.send({"op": "discard", "handle": handle})
            raise
        _publish_scalar(self, handle, value)
        return value

    @override
    def __getitem__(self, name: str) -> SharedCachedCollection[DocumentType]:
        database = self._database
        assert isinstance(database, SharedCachedDatabase)
        return type(self)(database, self._collection[name])

    @override
    def find_one(
        self,
        filter: object = None,
        projection: Mapping[str, Any] | Sequence[str] | None = None,
        *,
        collation: CollationInput | None = None,
        **kwargs: Any,
    ) -> DocumentType | None:
        self._shared._check_open()
        prepared = _default_identity_request(
            self, filter, projection, collation, kwargs
        )
        if prepared is not None:
            filter_query, identity, shape, prepared_reason = prepared
            reason: BypassReason | str | None = prepared_reason
            if reason is None:
                reason = self._cache_ineligibility_reason()
            if reason is None:
                return self._find_one_by_id(
                    identity, filter_query, projection, shape, sort=None, collation=None
                )
            self._shared.observation.record_bypass(reason)
        else:
            anchor, _remainder = extract_id_anchor(filter)
            if (
                anchor is not NO_IDENTITY
                and _shared_collation_reason(collation) is None
            ):
                return super().find_one(
                    filter, projection, collation=collation, **kwargs
                )
            return self._generic_find_one(filter, projection, collation, kwargs)
        return self.raw.find_one(filter, projection, collation=collation, **kwargs)

    def _generic_find_one(
        self,
        filter_query: object,
        projection: Mapping[str, Any] | Sequence[str] | None,
        collation: CollationInput | None,
        kwargs: Mapping[str, Any],
    ) -> DocumentType | None:
        options = dict(kwargs)
        session = options.pop("session", None)
        sort = options.pop("sort", None)
        filter_query = normalize_find_one_filter(filter_query)
        reason = self._request_bypass_reason(session=session, kwargs=options)
        if reason is None and not find_one_options_cacheable(sort, collation):
            reason = BypassReason.UNSUPPORTED_OPTIONS
        discriminator, classification = _scalar_key(
            self,
            "find_one",
            filter_query,
            projection,
            collation,
            options=sort,
            reason=reason,
        )
        return self._read_namespace(
            discriminator,
            reason or classification,
            lambda collection: collection.find_one(
                filter_query, projection, collation=collation, **kwargs
            ),
        )

    @override
    def find(self, *args: object, **kwargs: object) -> SharedCachedCursor[DocumentType]:
        self._shared._check_open()
        return SharedCachedCursor(self, *args, **kwargs)

    @override
    def _find_one_by_id(
        self,
        identity: object,
        filter_query: Mapping[str, Any],
        projection: Mapping[str, Any] | Sequence[str] | None,
        read_shape: object,
        *,
        sort: Sequence[tuple[str, int]] | None,
        collation: Any,
    ) -> DocumentType | None:
        keys = _identity_keys(self, identity, read_shape)
        document = _local_select(self, keys)
        if document is not NO_LOCAL_HIT and not isinstance(document, LocalMiss):
            return document  # type: ignore[return-value]
        endpoint = self._shared.endpoint
        value: object
        if isinstance(document, LocalMiss):
            outcome, value = "miss", document
        else:
            message = _identity_message(self, keys)
            reply = endpoint.request(message) if isinstance(message, dict) else None
            outcome, value = _identity_outcome(self, message, reply)
        if outcome == "hit":
            return value  # type: ignore[return-value]
        if outcome != "miss":
            return self._collection.find_one(
                filter_query, projection, sort=sort, collation=collation
            )
        try:
            document = self._forced_collection_handle().find_one(
                filter_query, projection, sort=sort, collation=collation
            )
        except BaseException:
            if value is not None and not isinstance(value, LocalMiss):
                endpoint.send({"op": "discard", "handle": value})
            raise
        if value is not None:
            admission = _admission(
                value,
                document,
                self._collection.codec_options,
                self._shared.max_entry_bytes,
                self._shared.observation,
            )
            if admission is not None:
                endpoint.send(
                    admission, value.reader if isinstance(value, LocalMiss) else None
                )
        return document

    @override
    def aggregate(
        self,
        pipeline: Sequence[Mapping[str, Any]],
        session: ClientSession | None = None,
        let: Mapping[str, Any] | None = None,
        comment: object = None,
        **kwargs: object,
    ) -> CommandCursor[DocumentType]:
        self._shared._check_open()
        unsupported = dict(kwargs)
        collation = unsupported.pop("collation", None)
        if let is not None:
            unsupported["let"] = let
        if comment is not None:
            unsupported["comment"] = comment
        reason: BypassReason | str | None = self._request_bypass_reason(
            session=session, kwargs=unsupported
        )
        if reason is not None:
            self._shared.observation.record_bypass(reason)
            return self.raw.aggregate(
                pipeline, session=session, let=let, comment=comment, **kwargs
            )
        collation = sync_cursors.prepare_aggregate(self, pipeline, kwargs)
        reason = _shared_collation_reason(collation)
        discriminator = order_sensitive_discriminator_key(
            (
                "aggregate",
                pipeline,
                collation,
                self._codec_identity,
            )
        )
        discriminator, classification = prepare_pipeline_key(pipeline, discriminator)
        reason = reason or classification
        if reason is None:
            reason = self._cache_ineligibility_reason()
        if reason is not None:
            self._shared.observation.record_bypass(reason)
            return self.raw.aggregate(
                pipeline, session=session, let=let, comment=comment, **kwargs
            )
        message = _namespace_message(self, discriminator)
        snapshot = _namespace_local(self, message)
        if snapshot is NO_LOCAL_HIT:
            reply = (
                self._shared.endpoint.request(message)
                if isinstance(message, dict)
                else None
            )
            outcome, handle = _identity_outcome(self, message, reply)
            if outcome == "hit":
                snapshot = handle
            elif outcome == "miss" and handle is not None:
                capture = _remote_capture(self, handle, discriminator)
                try:
                    return sync_cursors.aggregate_miss(self, pipeline, capture, kwargs)
                except BaseException:
                    capture.abandon()
                    raise
            else:
                return self.raw.aggregate(
                    pipeline, session=session, let=let, comment=comment, **kwargs
                )
        return sync_cursors.CachedCommandCursor(
            self.raw, {"id": 0, "firstBatch": snapshot, "ns": self.raw.full_name}, None
        )

    @override
    def count_documents(
        self,
        filter: Mapping[str, Any],
        *,
        session: ClientSession | None = None,
        **kwargs: object,
    ) -> NonNegativeInt:
        options = count_read_options(kwargs)
        reason = self._request_bypass_reason(
            session=session, kwargs=options["extra_options"]
        )
        discriminator, classification = _count_key(
            self, filter, options["cache_options"], reason=reason
        )
        return self._read_namespace(
            discriminator,
            reason or classification,
            lambda collection: collection.count_documents(
                filter, session=session, **kwargs
            ),
        )

    @override
    def estimated_document_count(self, **kwargs: object) -> NonNegativeInt:
        reason = self._request_bypass_reason(session=None, kwargs=kwargs)
        discriminator = canonicalize(("estimated_document_count", self._codec_identity))
        return self._read_namespace(
            discriminator,
            reason,
            lambda collection: collection.estimated_document_count(**kwargs),
        )

    @override
    def distinct(
        self,
        key: str,
        filter: Mapping[str, Any] | None = None,
        *,
        collation: CollationInput | None = None,
        session: ClientSession | None = None,
        **kwargs: object,
    ) -> list[Any]:
        reason = self._request_bypass_reason(session=session, kwargs=kwargs)
        native_options: Mapping[str, Any] = kwargs
        discriminator, classification = _scalar_key(
            self, "distinct", filter, None, collation, options=key, reason=reason
        )
        return self._read_namespace(
            discriminator,
            reason or classification,
            lambda collection: collection.distinct(
                key, filter, collation=collation, session=session, **native_options
            ),
        )


class AsyncSharedCachedCollection[DocumentType: Mapping[str, Any]](
    async_collection.CachedCollection[DocumentType]
):
    __slots__ = ("_default_shape_key", "_shared")

    def __init__(
        self,
        database: AsyncSharedCachedDatabase[DocumentType],
        collection: AsyncCollection[DocumentType],
    ) -> None:
        super().__init__(database, collection)
        self._shared: AsyncSharedCacheManager[DocumentType] = database.shared
        self._default_shape_key = _default_shape_key(self)

    async def _read_namespace[Value](
        self,
        discriminator: object,
        reason: BypassReason | str | None,
        read: Callable[[AsyncCollection[DocumentType]], Awaitable[Value]],
    ) -> Value:
        self._shared._check_open()
        if reason is None:
            reason = await self._cache_ineligibility_reason()
        if reason is not None:
            self._shared.observation.record_bypass(reason)
            return await read(self.raw)
        message = _namespace_message(self, discriminator)
        snapshot = _namespace_local(self, message)
        if snapshot is not NO_LOCAL_HIT:
            return snapshot  # type: ignore[return-value]
        reply = (
            await self._shared.endpoint.request(message)
            if isinstance(message, dict)
            else None
        )
        outcome, handle = _identity_outcome(self, message, reply)
        if outcome == "hit":
            return handle  # type: ignore[return-value]
        if outcome != "miss":
            return await read(self.raw)
        try:
            value = await read(self._forced_collection_handle())
        except BaseException:
            if handle is not None:
                self._shared.endpoint.send({"op": "discard", "handle": handle})
            raise
        _publish_scalar(self, handle, value)
        return value

    @override
    def __getitem__(self, name: str) -> AsyncSharedCachedCollection[DocumentType]:
        database = self._database
        assert isinstance(database, AsyncSharedCachedDatabase)
        return type(self)(database, self._collection[name])

    @override
    async def find_one(
        self,
        filter: object = None,
        projection: Mapping[str, Any] | Sequence[str] | None = None,
        *,
        collation: CollationInput | None = None,
        **kwargs: Any,
    ) -> DocumentType | None:
        self._shared._check_open()
        prepared = _default_identity_request(
            self, filter, projection, collation, kwargs
        )
        if prepared is not None:
            filter_query, identity, shape, prepared_reason = prepared
            reason: BypassReason | str | None = prepared_reason
            if reason is None:
                reason = await self._cache_ineligibility_reason()
            if reason is None:
                return await self._find_one_by_id(
                    identity, filter_query, projection, shape, sort=None, collation=None
                )
            self._shared.observation.record_bypass(reason)
        else:
            anchor, _remainder = extract_id_anchor(filter)
            if (
                anchor is not NO_IDENTITY
                and _shared_collation_reason(collation) is None
            ):
                return await super().find_one(
                    filter, projection, collation=collation, **kwargs
                )
            return await self._generic_find_one(filter, projection, collation, kwargs)
        return await self.raw.find_one(
            filter, projection, collation=collation, **kwargs
        )

    async def _generic_find_one(
        self,
        filter_query: object,
        projection: Mapping[str, Any] | Sequence[str] | None,
        collation: CollationInput | None,
        kwargs: Mapping[str, Any],
    ) -> DocumentType | None:
        options = dict(kwargs)
        session = options.pop("session", None)
        sort = options.pop("sort", None)
        filter_query = normalize_find_one_filter(filter_query)
        reason = self._request_bypass_reason(session=session, kwargs=options)
        if reason is None and not find_one_options_cacheable(sort, collation):
            reason = BypassReason.UNSUPPORTED_OPTIONS
        discriminator, classification = _scalar_key(
            self,
            "find_one",
            filter_query,
            projection,
            collation,
            options=sort,
            reason=reason,
        )
        return await self._read_namespace(
            discriminator,
            reason or classification,
            lambda collection: collection.find_one(
                filter_query, projection, collation=collation, **kwargs
            ),
        )

    @override
    def find(
        self, *args: object, **kwargs: object
    ) -> AsyncSharedCachedCursor[DocumentType]:
        self._shared._check_open()
        return AsyncSharedCachedCursor(self, *args, **kwargs)

    @override
    async def _find_one_by_id(
        self,
        identity: object,
        filter_query: Mapping[str, Any],
        projection: Mapping[str, Any] | Sequence[str] | None,
        read_shape: object,
        *,
        sort: Sequence[tuple[str, int]] | None,
        collation: Any,
    ) -> DocumentType | None:
        keys = _identity_keys(self, identity, read_shape)
        document = _local_select(self, keys)
        if document is not NO_LOCAL_HIT and not isinstance(document, LocalMiss):
            return document  # type: ignore[return-value]
        endpoint = self._shared.endpoint
        value: object
        if isinstance(document, LocalMiss):
            outcome, value = "miss", document
        else:
            message = _identity_message(self, keys)
            reply = (
                await endpoint.request(message) if isinstance(message, dict) else None
            )
            outcome, value = _identity_outcome(self, message, reply)
        if outcome == "hit":
            return value  # type: ignore[return-value]
        if outcome != "miss":
            return await self._collection.find_one(
                filter_query, projection, sort=sort, collation=collation
            )
        try:
            document = await self._forced_collection_handle().find_one(
                filter_query, projection, sort=sort, collation=collation
            )
        except BaseException:
            if value is not None and not isinstance(value, LocalMiss):
                endpoint.send({"op": "discard", "handle": value})
            raise
        if value is not None:
            admission = _admission(
                value,
                document,
                self._collection.codec_options,
                self._shared.max_entry_bytes,
                self._shared.observation,
            )
            if admission is not None:
                endpoint.send(
                    admission, value.reader if isinstance(value, LocalMiss) else None
                )
        return document

    @override
    async def aggregate(
        self,
        pipeline: Sequence[Mapping[str, Any]],
        session: AsyncClientSession | None = None,
        let: Mapping[str, Any] | None = None,
        comment: object = None,
        **kwargs: object,
    ) -> AsyncCommandCursor[DocumentType]:
        self._shared._check_open()
        unsupported = dict(kwargs)
        collation = unsupported.pop("collation", None)
        if let is not None:
            unsupported["let"] = let
        if comment is not None:
            unsupported["comment"] = comment
        reason: BypassReason | str | None = self._request_bypass_reason(
            session=session, kwargs=unsupported
        )
        if reason is not None:
            self._shared.observation.record_bypass(reason)
            return await self.raw.aggregate(
                pipeline, session=session, let=let, comment=comment, **kwargs
            )
        collation = async_cursors.prepare_aggregate(self, pipeline, kwargs)
        reason = _shared_collation_reason(collation)
        discriminator = order_sensitive_discriminator_key(
            (
                "aggregate",
                pipeline,
                collation,
                self._codec_identity,
            )
        )
        discriminator, classification = prepare_pipeline_key(pipeline, discriminator)
        reason = reason or classification
        if reason is None:
            reason = await self._cache_ineligibility_reason()
        if reason is not None:
            self._shared.observation.record_bypass(reason)
            return await self.raw.aggregate(
                pipeline, session=session, let=let, comment=comment, **kwargs
            )
        message = _namespace_message(self, discriminator)
        snapshot = _namespace_local(self, message)
        if snapshot is NO_LOCAL_HIT:
            reply = (
                await self._shared.endpoint.request(message)
                if isinstance(message, dict)
                else None
            )
            outcome, handle = _identity_outcome(self, message, reply)
            if outcome == "hit":
                snapshot = handle
            elif outcome == "miss" and handle is not None:
                capture = _remote_capture(self, handle, discriminator)
                try:
                    return await async_cursors.aggregate_miss(
                        self, pipeline, capture, kwargs
                    )
                except BaseException:
                    capture.abandon()
                    raise
            else:
                return await self.raw.aggregate(
                    pipeline, session=session, let=let, comment=comment, **kwargs
                )
        return async_cursors.CachedCommandCursor(
            self.raw, {"id": 0, "firstBatch": snapshot, "ns": self.raw.full_name}, None
        )

    @override
    async def count_documents(
        self,
        filter: Mapping[str, Any],
        *,
        session: AsyncClientSession | None = None,
        **kwargs: object,
    ) -> NonNegativeInt:
        options = count_read_options(kwargs)
        reason = self._request_bypass_reason(
            session=session, kwargs=options["extra_options"]
        )
        discriminator, classification = _count_key(
            self, filter, options["cache_options"], reason=reason
        )
        return await self._read_namespace(
            discriminator,
            reason or classification,
            lambda collection: collection.count_documents(
                filter, session=session, **kwargs
            ),
        )

    @override
    async def estimated_document_count(self, **kwargs: object) -> NonNegativeInt:
        reason = self._request_bypass_reason(session=None, kwargs=kwargs)
        discriminator = canonicalize(("estimated_document_count", self._codec_identity))
        return await self._read_namespace(
            discriminator,
            reason,
            lambda collection: collection.estimated_document_count(**kwargs),
        )

    @override
    async def distinct(
        self,
        key: str,
        filter: Mapping[str, Any] | None = None,
        *,
        collation: CollationInput | None = None,
        session: AsyncClientSession | None = None,
        **kwargs: object,
    ) -> list[Any]:
        reason = self._request_bypass_reason(session=session, kwargs=kwargs)
        native_options: Mapping[str, Any] = kwargs
        discriminator, classification = _scalar_key(
            self, "distinct", filter, None, collation, options=key, reason=reason
        )
        return await self._read_namespace(
            discriminator,
            reason or classification,
            lambda collection: collection.distinct(
                key, filter, collation=collation, session=session, **native_options
            ),
        )


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
        return self.shared.get_cached_collection(self._database[name])


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
        return self.shared.get_cached_collection(self._database[name])


class SharedCacheManager[DocumentType: Mapping[str, Any]]:
    __slots__ = (
        "_client",
        "_closed",
        "_metadata",
        "_reattach",
        "_reattach_after",
        "_reattaching",
        "_slots",
        "endpoint",
        "keys",
        "local",
        "max_entry_bytes",
        "observation",
    )

    def __init__(
        self,
        client: MongoClient[DocumentType],
        endpoint: SyncEndpoint,
        local: LocalIndex | None = None,
    ) -> None:
        self._client = client
        self._closed = False
        self.endpoint = endpoint
        self.local = local
        self.max_entry_bytes = endpoint.config.max_entry_bytes
        self.observation = LocalObservation()
        self.keys = KeyCache(_KEY_CACHE_ENTRIES)
        self._metadata = NamespaceMetadataCache[CollectionMetadata](
            endpoint.config.max_namespaces
        )
        self._slots = NamespaceMetadataCache[
            tuple[NonNegativeInt, NonNegativeInt, object]
        ](endpoint.config.max_namespaces)
        self._reattach = False
        self._reattach_after = 0.0
        self._reattaching = threading.Lock()

    def _check_open(self) -> None:
        self.endpoint._check_owner()
        if self._closed:
            raise CacheClosedError("the shared cache manager is closed")

    def snapshot(self) -> SharedCacheStatistics:
        return SharedCacheStatistics(
            self.observation.hits,
            self.observation.misses,
            sum(self.observation.bypasses.values()),
        )

    @property
    def client(self) -> MongoClient[DocumentType]:
        return self._client

    @property
    def cache_core(self) -> LocalObservation:
        return self.observation

    def _reattach_local(self, local: LocalIndex | None) -> None:
        if not self._reattaching.acquire(blocking=False):
            return
        try:
            if self.local is not local:
                return
            try:
                replacement = LocalIndex.attach(self.endpoint.config)
            except OSError as error:
                if not attachment_unavailable(error):
                    raise
                self._reattach_after = time.monotonic() + _REATTACH_SECONDS
                return
            self.local = replacement
            _reattached(self)
        finally:
            self._reattaching.release()
        if local is not None:
            local.close()

    def _cache_ineligibility_reason(
        self,
        namespace: NamespaceId,
        probe: Callable[[], CollectionProbeResult | None],
    ) -> BypassReason | str | None:
        if (
            self._reattach
            and (self.local is not None or self.endpoint.connected)
            and time.monotonic() >= self._reattach_after
        ):
            self._reattach_local(self.local)
        cached = _cached_metadata(self._metadata, namespace)
        if cached is not None and cached is not _STALE:
            return cached.bypass_reason or (
                PROTOTYPE_SCOPE if cached.default_collation is not None else None
            )
        metadata_version = self._metadata.version
        capacity = self.endpoint.request(
            {
                "op": "metadata-probe",
                "ns": [namespace.database, namespace.collection],
            }
        )
        if capacity is None:
            return OWNER_UNAVAILABLE
        if capacity["r"] == "bypass":
            if capacity["reason"] == "namespace_capacity":
                self._metadata.put_if_version(
                    namespace,
                    CollectionMetadata(
                        checked_epoch=0,
                        bypass_reason=BypassReason.NAMESPACE_CAPACITY,
                        default_collation=None,
                        epoch_bound=False,
                        expires_at=(time.monotonic() + _NEGATIVE_METADATA_TTL_SECONDS),
                    ),
                    metadata_version,
                )
            return str(capacity["reason"])
        assert capacity["r"] == "probe"
        probe_token = _metadata_probe_token(capacity)
        metadata_requested = False
        try:
            probe_result = probe()
            if probe_result is None:
                return BypassReason.METADATA_UNAVAILABLE
            probe_reason = probe_result.bypass_reason
            if probe_reason is BypassReason.MISSING_COLLECTION:
                return probe_reason
            if probe_reason is not None:
                self._metadata.put_if_version(
                    namespace,
                    CollectionMetadata(
                        checked_epoch=0,
                        bypass_reason=probe_reason,
                        default_collation=probe_result.default_collation,
                        epoch_bound=False,
                        expires_at=(time.monotonic() + _NEGATIVE_METADATA_TTL_SECONDS),
                    ),
                    metadata_version,
                )
                return probe_reason
            metadata_requested = True
            reply = self.endpoint.request(
                {
                    "op": "metadata",
                    "ns": [namespace.database, namespace.collection],
                    "probe_token": probe_token,
                }
            )
            metadata = _metadata(reply, probe_result)
            if not isinstance(metadata, CollectionMetadata):
                return metadata
            assert reply is not None
            _remember_slot(self, namespace, reply)
            self._metadata.store(namespace, metadata)
            return metadata.bypass_reason or (
                PROTOTYPE_SCOPE if metadata.default_collation is not None else None
            )
        finally:
            if not metadata_requested:
                self.endpoint.request(
                    {
                        "op": "metadata-cancel",
                        "ns": [namespace.database, namespace.collection],
                        "probe_token": probe_token,
                    }
                )

    def _default_collation_for(
        self, namespace: NamespaceId
    ) -> Mapping[str, Any] | None:
        metadata = _cached_metadata(self._metadata, namespace)
        return None if metadata is None else metadata.default_collation

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
        self.endpoint._check_owner()
        if self._closed:
            return
        self._closed = True
        if self.local is not None:
            self.local.close()
        self.endpoint.close()


class AsyncSharedCacheManager[DocumentType: Mapping[str, Any]]:
    __slots__ = (
        "_client",
        "_closed",
        "_metadata",
        "_reattach",
        "_reattach_after",
        "_reattaching",
        "_slots",
        "endpoint",
        "keys",
        "local",
        "max_entry_bytes",
        "observation",
    )

    def __init__(
        self,
        client: AsyncMongoClient[DocumentType],
        endpoint: AsyncEndpoint,
        local: AsyncLocalIndex | None = None,
    ) -> None:
        self._client = client
        self._closed = False
        self.endpoint = endpoint
        self.local = local
        self.max_entry_bytes = endpoint.config.max_entry_bytes
        self.observation = LocalObservation()
        self.keys = KeyCache(_KEY_CACHE_ENTRIES)
        self._metadata = NamespaceMetadataCache[CollectionMetadata](
            endpoint.config.max_namespaces
        )
        self._slots = NamespaceMetadataCache[
            tuple[NonNegativeInt, NonNegativeInt, object]
        ](endpoint.config.max_namespaces)
        self._reattach = False
        self._reattach_after = 0.0
        self._reattaching = asyncio.Lock()

    def _check_open(self) -> None:
        self.endpoint._check_owner()
        if self._closed:
            raise CacheClosedError("the shared cache manager is closed")

    def snapshot(self) -> SharedCacheStatistics:
        return SharedCacheStatistics(
            self.observation.hits,
            self.observation.misses,
            sum(self.observation.bypasses.values()),
        )

    @property
    def client(self) -> AsyncMongoClient[DocumentType]:
        return self._client

    @property
    def cache_core(self) -> LocalObservation:
        return self.observation

    async def _reattach_local(self, local: AsyncLocalIndex | None) -> None:
        if self._reattaching.locked():
            return
        async with self._reattaching:
            if self.local is not local:
                return
            try:
                replacement = await AsyncLocalIndex.attach(self.endpoint.config)
            except OSError as error:
                if not attachment_unavailable(error):
                    raise
                self._reattach_after = time.monotonic() + _REATTACH_SECONDS
                return
            self.local = replacement
            _reattached(self)
        if local is not None:
            await local.close()

    async def _cache_ineligibility_reason(
        self,
        namespace: NamespaceId,
        probe: Callable[[], Awaitable[CollectionProbeResult | None]],
    ) -> BypassReason | str | None:
        if (
            self._reattach
            and (self.local is not None or self.endpoint.connected)
            and time.monotonic() >= self._reattach_after
        ):
            await self._reattach_local(self.local)
        cached = _cached_metadata(self._metadata, namespace)
        if cached is not None and cached is not _STALE:
            return cached.bypass_reason or (
                PROTOTYPE_SCOPE if cached.default_collation is not None else None
            )
        metadata_version = self._metadata.version
        capacity = await self.endpoint.request(
            {
                "op": "metadata-probe",
                "ns": [namespace.database, namespace.collection],
            }
        )
        if capacity is None:
            return OWNER_UNAVAILABLE
        if capacity["r"] == "bypass":
            if capacity["reason"] == "namespace_capacity":
                self._metadata.put_if_version(
                    namespace,
                    CollectionMetadata(
                        checked_epoch=0,
                        bypass_reason=BypassReason.NAMESPACE_CAPACITY,
                        default_collation=None,
                        epoch_bound=False,
                        expires_at=(time.monotonic() + _NEGATIVE_METADATA_TTL_SECONDS),
                    ),
                    metadata_version,
                )
            return str(capacity["reason"])
        assert capacity["r"] == "probe"
        probe_token = _metadata_probe_token(capacity)
        metadata_requested = False
        try:
            probe_result = await probe()
            if probe_result is None:
                return BypassReason.METADATA_UNAVAILABLE
            probe_reason = probe_result.bypass_reason
            if probe_reason is BypassReason.MISSING_COLLECTION:
                return probe_reason
            if probe_reason is not None:
                self._metadata.put_if_version(
                    namespace,
                    CollectionMetadata(
                        checked_epoch=0,
                        bypass_reason=probe_reason,
                        default_collation=probe_result.default_collation,
                        epoch_bound=False,
                        expires_at=(time.monotonic() + _NEGATIVE_METADATA_TTL_SECONDS),
                    ),
                    metadata_version,
                )
                return probe_reason
            metadata_requested = True
            reply = await self.endpoint.request(
                {
                    "op": "metadata",
                    "ns": [namespace.database, namespace.collection],
                    "probe_token": probe_token,
                }
            )
            metadata = _metadata(reply, probe_result)
            if not isinstance(metadata, CollectionMetadata):
                return metadata
            assert reply is not None
            _remember_slot(self, namespace, reply)
            self._metadata.store(namespace, metadata)
            return metadata.bypass_reason or (
                PROTOTYPE_SCOPE if metadata.default_collation is not None else None
            )
        finally:
            if not metadata_requested:
                await self.endpoint.request(
                    {
                        "op": "metadata-cancel",
                        "ns": [namespace.database, namespace.collection],
                        "probe_token": probe_token,
                    }
                )

    def _default_collation_for(
        self, namespace: NamespaceId
    ) -> Mapping[str, Any] | None:
        metadata = _cached_metadata(self._metadata, namespace)
        return None if metadata is None else metadata.default_collation

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
        self.endpoint._check_owner()
        self._closed = True
        if self.local is not None:
            await self.local.close()
        await self.endpoint.close()
