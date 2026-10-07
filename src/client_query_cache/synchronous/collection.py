from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, cast

from pymongo import ReadPreference
from pymongo.collation import Collation
from pymongo.errors import PyMongoError
from pymongo.read_concern import ReadConcern
from pymongo.synchronous.collection import Collection

from client_query_cache._core.canonical import canonicalize, is_canonicalizable
from client_query_cache._core.codec import codec_fingerprint
from client_query_cache._core.collation import collation_document
from client_query_cache._core.collection_metadata import (
    interpret_list_collections_entry,
)
from client_query_cache._core.count_reads import count_read_options
from client_query_cache._core.cursor_capture import CursorCapture
from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.errors import UnsupportedCacheRequestError
from client_query_cache._core.find_one_reads import (
    effective_find_one_collation,
    find_one_read_shape,
    generic_find_one_discriminator,
    normalize_find_one_filter,
)
from client_query_cache._core.identity_reads import (
    NO_IDENTITY,
    extract_id_identity,
    normalize_identity_for_cache_key,
)
from client_query_cache._core.keys import NamespaceId, canonical_alias_key
from client_query_cache._core.order_sensitive_keys import (
    order_sensitive_discriminator_key,
)
from client_query_cache._core.projection import (
    ensure_id_present_for_resolution,
    without_id,
)
from client_query_cache._core.read_classification import (
    find_one_bypass_reason,
    pipeline_bypass_reason,
    query_bypass_reason,
    request_bypass_reason,
)
from client_query_cache._core.snapshots import BypassReason
from client_query_cache._core.traversal import (
    declared_attribute_names,
    ensure_subcollection_name,
)
from client_query_cache._core.unique_keys import match_unique_key
from client_query_cache.synchronous.cursors import (
    CachedCommandCursor,
    CachedCursor,
    aggregate_miss,
    prepare_aggregate,
)

if TYPE_CHECKING:
    from pymongo.client_session import ClientSession
    from pymongo.synchronous.command_cursor import CommandCursor
    from pymongo.synchronous.cursor import Cursor
    from pymongo.synchronous.database import Database

    from client_query_cache._core.collection_metadata import CollectionProbeResult
    from client_query_cache._core.keys import AliasKey
    from client_query_cache._core.unique_keys import UniqueKeyDefinition
    from client_query_cache.synchronous.database import CachedDatabase

_FORCED_READ_CONCERN = ReadConcern("majority")
_COLLECTION_ATTRIBUTE_NAMES = declared_attribute_names(Collection)

logger = logging.getLogger(__name__)

type _CollationIn = Collation | Mapping[str, Any]


class CachedCollection[DocumentType: Mapping[str, Any]]:
    __slots__ = (
        "_collection",
        "_database",
        "_find_one_default_shape",
        "_forced_collection",
        "_forced_database",
    )

    def __init__(
        self,
        database: CachedDatabase[DocumentType],
        collection: Collection[DocumentType],
    ) -> None:
        self._database = database
        self._collection = collection
        default_shape = find_one_read_shape(
            None, None, None, codec_fingerprint(collection.codec_options)
        )
        try:
            self._find_one_default_shape = canonicalize(default_shape)
        except UnsupportedCacheRequestError:
            self._find_one_default_shape = default_shape
        self._forced_collection: Collection[DocumentType] | None = None
        self._forced_database: Database[DocumentType] | None = None

    @property
    def database(self) -> CachedDatabase[DocumentType]:
        return self._database

    @property
    def name(self) -> str:
        return self._collection.name

    @property
    def raw(self) -> Collection[DocumentType]:
        return self._collection

    def __getitem__(self, name: str) -> CachedCollection[DocumentType]:
        return CachedCollection(self._database, self._collection[name])

    def __getattr__(self, name: str) -> CachedCollection[DocumentType]:
        ensure_subcollection_name(self, name, _COLLECTION_ATTRIBUTE_NAMES)
        return self[name]

    def find_one(
        self,
        filter: object = None,  # noqa: A002
        projection: Mapping[str, Any] | Sequence[str] | None = None,
        *,
        sort: Sequence[tuple[str, int]] | None = None,
        collation: _CollationIn | None = None,
        session: ClientSession | None = None,
        **kwargs: object,
    ) -> DocumentType | None:
        filter_query = normalize_find_one_filter(filter)
        reason = self._request_bypass_reason(
            session=session, kwargs=kwargs
        ) or find_one_bypass_reason(filter_query, projection, sort, collation)
        codec_options = self._collection.codec_options
        filter_key: object = filter_query
        if reason is None:
            identity = extract_id_identity(filter)
            explicit_collation = effective_find_one_collation(collation, None)
            try:
                read_shape = (
                    canonicalize(self._find_one_default_shape)
                    if projection is None
                    and sort is None
                    and explicit_collation is None
                    else canonicalize(
                        find_one_read_shape(
                            projection,
                            sort,
                            explicit_collation,
                            codec_fingerprint(codec_options),
                        )
                    )
                )
                if identity is NO_IDENTITY:
                    filter_key = canonicalize(
                        order_sensitive_discriminator_key(filter_query)
                    )
                elif not is_canonicalizable(identity):
                    reason = BypassReason.UNCANONICALIZABLE_KEY
            except UnsupportedCacheRequestError:
                reason = BypassReason.UNCANONICALIZABLE_KEY
        if reason is None:
            reason = self._cache_ineligibility_reason()
        if reason is not None:
            self._record_bypass(reason)
            return self._collection.find_one(
                filter,
                projection,
                sort=sort,
                collation=collation,
                session=session,
                **kwargs,
            )
        effective_collation = effective_find_one_collation(
            collation,
            self._database.manager._default_collation_for(self._namespace()),  # noqa: SLF001
        )
        if collation is None and effective_collation is not None:
            read_shape = canonicalize(
                find_one_read_shape(
                    projection,
                    sort,
                    effective_collation,
                    codec_fingerprint(codec_options),
                )
            )
        if identity is not NO_IDENTITY and effective_collation is None:
            return self._find_one_by_id(
                identity, projection, read_shape, sort=sort, collation=collation
            )
        namespace = self._namespace()
        cache = self._database.manager.cache_core
        known_keys = self._database.manager._unique_keys_for(namespace)  # noqa: SLF001
        unique_key_match = (
            match_unique_key(filter_query, known_keys, effective_collation)
            if identity is NO_IDENTITY and known_keys is not None
            else None
        )
        if unique_key_match is None:
            discriminator = canonicalize(
                generic_find_one_discriminator(
                    filter_key,
                    read_shape,
                    cache.current_index_generation(namespace),
                )
            )
            lookup_result = cache.lookup_namespace(
                namespace, discriminator, codec_options=codec_options
            )
            if lookup_result.hit:
                return cast("DocumentType | None", lookup_result.value)
            if identity is NO_IDENTITY and known_keys is None:
                unique_key_match = self._match_unique_key(
                    filter_query, effective_collation
                )
        if unique_key_match is not None:
            key_definition, key_values = unique_key_match
            return self._find_one_by_unique_key(
                key_definition,
                key_values,
                filter_query,
                projection,
                read_shape,
                sort=sort,
                collation=collation,
            )
        if not cache.is_database_available(namespace.database):
            return self._collection.find_one(
                filter, projection, sort=sort, collation=collation, session=session
            )
        capture = cache.capture_namespace_generation(namespace)
        document = self._forced_collection_handle().find_one(
            filter, projection, sort=sort, collation=collation
        )
        cache.admit_namespace(
            capture, discriminator, document, codec_options=codec_options
        )
        return document

    def find(self, *args: object, **kwargs: object) -> Cursor[DocumentType]:
        return CachedCursor(self, *args, **kwargs)

    def aggregate(
        self,
        pipeline: Sequence[Mapping[str, Any]],
        session: ClientSession | None = None,
        let: Mapping[str, Any] | None = None,
        comment: object = None,
        **kwargs: object,
    ) -> CommandCursor[DocumentType]:
        unsupported = dict(kwargs)
        unsupported.pop("collation", None)
        if let is not None:
            unsupported["let"] = let
        if comment is not None:
            unsupported["comment"] = comment
        reason = self._request_bypass_reason(session=session, kwargs=unsupported)
        if reason is not None:
            self._record_bypass(reason)
            return self.raw.aggregate(
                pipeline,
                session=session,
                let=let,
                comment=comment,
                **cast("dict[str, Any]", kwargs),
            )
        # Use native local preparation before lookup, including on a warm entry.
        collation = prepare_aggregate(self, pipeline, kwargs)
        codec_options = self.raw.codec_options
        discriminator = order_sensitive_discriminator_key(
            (
                "aggregate",
                pipeline,
                collation,
                codec_fingerprint(codec_options),
            )
        )
        reason = (
            pipeline_bypass_reason(pipeline, discriminator)
            or self._cache_ineligibility_reason()
        )
        if reason is not None:
            self._record_bypass(reason)
            return self.raw.aggregate(
                pipeline,
                session=session,
                let=let,
                comment=comment,
                **cast("dict[str, Any]", kwargs),
            )
        namespace = self._namespace()
        cache = self.database.manager.cache_core
        lookup = cache.lookup_namespace(
            namespace, discriminator, codec_options=codec_options
        )
        if lookup.hit:
            return CachedCommandCursor(
                self.raw,
                {"id": 0, "firstBatch": lookup.value, "ns": self.raw.full_name},
                None,
            )
        if not cache.is_database_available(namespace.database):
            return self.raw.aggregate(
                pipeline,
                session=session,
                let=let,
                comment=comment,
                **cast("dict[str, Any]", kwargs),
            )
        capture = CursorCapture(
            cache,
            cache.capture_namespace_generation(namespace),
            discriminator,
            codec_options,
        )
        return aggregate_miss(self, pipeline, capture, kwargs)

    def count_documents(
        self,
        filter: Mapping[str, Any],  # noqa: A002
        *,
        session: ClientSession | None = None,
        **kwargs: object,
    ) -> int:
        options = count_read_options(kwargs)
        codec_options = self._collection.codec_options
        discriminator = order_sensitive_discriminator_key(
            (
                "count_documents",
                filter,
                *options["cache_options"],
                codec_fingerprint(codec_options),
            )
        )
        reason = (
            self._request_bypass_reason(
                session=session, kwargs=options["extra_options"]
            )
            or query_bypass_reason(filter, None, discriminator)
            or self._cache_ineligibility_reason()
        )
        if reason is not None:
            self._record_bypass(reason)
            return self._collection.count_documents(filter, session=session, **kwargs)
        namespace = self._namespace()
        cache = self._database.manager.cache_core
        lookup_result = cache.lookup_namespace(
            namespace, discriminator, codec_options=codec_options
        )
        if lookup_result.hit:
            return cast("int", lookup_result.value)
        if not cache.is_database_available(namespace.database):
            return self._collection.count_documents(filter, session=session, **kwargs)
        capture = cache.capture_namespace_generation(namespace)
        count = self._forced_collection_handle().count_documents(
            filter, session=session, **kwargs
        )
        cache.admit_namespace(
            capture, discriminator, count, codec_options=codec_options
        )
        return count

    def estimated_document_count(self, **kwargs: object) -> int:
        reason = (
            self._request_bypass_reason(session=None, kwargs=kwargs)
            or self._cache_ineligibility_reason()
        )
        if reason is not None:
            self._record_bypass(reason)
            return self._collection.estimated_document_count(**kwargs)
        namespace = self._namespace()
        discriminator = ("estimated_document_count",)
        cache = self._database.manager.cache_core
        codec_options = self._collection.codec_options
        lookup_result = cache.lookup_namespace(
            namespace, discriminator, codec_options=codec_options
        )
        if lookup_result.hit:
            return cast("int", lookup_result.value)
        if not cache.is_database_available(namespace.database):
            return self._collection.estimated_document_count()
        capture = cache.capture_namespace_generation(namespace)
        count = self._forced_collection_handle().estimated_document_count()
        cache.admit_namespace(
            capture, discriminator, count, codec_options=codec_options
        )
        return count

    def distinct(
        self,
        key: str,
        filter: Mapping[str, Any] | None = None,  # noqa: A002
        *,
        collation: _CollationIn | None = None,
        session: ClientSession | None = None,
        **kwargs: object,
    ) -> list[Any]:
        codec_options = self._collection.codec_options
        discriminator = order_sensitive_discriminator_key(
            (
                "distinct",
                key,
                filter,
                collation_document(collation),
                codec_fingerprint(codec_options),
            )
        )
        reason = (
            self._request_bypass_reason(session=session, kwargs=kwargs)
            or query_bypass_reason(filter, None, discriminator)
            or self._cache_ineligibility_reason()
        )
        if reason is not None:
            self._record_bypass(reason)
            return self._collection.distinct(
                key,
                filter,
                collation=collation,
                session=session,
                **cast("dict[str, Any]", kwargs),
            )
        namespace = self._namespace()
        cache = self._database.manager.cache_core
        lookup_result = cache.lookup_namespace(
            namespace, discriminator, codec_options=codec_options
        )
        if lookup_result.hit:
            return cast("list[Any]", lookup_result.value)
        if not cache.is_database_available(namespace.database):
            return self._collection.distinct(
                key,
                filter,
                collation=collation,
                session=session,
                **cast("dict[str, Any]", kwargs),
            )
        capture = cache.capture_namespace_generation(namespace)
        values = self._forced_collection_handle().distinct(
            key, filter, collation=collation
        )
        cache.admit_namespace(
            capture, discriminator, values, codec_options=codec_options
        )
        return values

    def _find_one_by_id(
        self,
        identity: object,
        projection: Mapping[str, Any] | Sequence[str] | None,
        read_shape: object,
        *,
        sort: Sequence[tuple[str, int]] | None,
        collation: _CollationIn | None,
    ) -> DocumentType | None:
        namespace = self._namespace()
        cache = self._database.manager.cache_core
        codec_options = self._collection.codec_options
        cache_identity = normalize_identity_for_cache_key(
            identity, codec_options, self._database.manager.client.codec_options
        )
        if not is_canonicalizable(cache_identity):
            self._record_bypass(BypassReason.UNCANONICALIZABLE_KEY)
            return self._collection.find_one(
                {"_id": identity}, projection, sort=sort, collation=collation
            )
        lookup_result = cache.lookup_identity(
            namespace, cache_identity, read_shape, codec_options=codec_options
        )
        if lookup_result.hit:
            return cast("DocumentType | None", lookup_result.value)
        if not cache.is_database_available(namespace.database):
            return self._collection.find_one(
                {"_id": identity}, projection, sort=sort, collation=collation
            )
        capture = cache.begin_identity_admission(namespace, cache_identity)
        try:
            document = self._forced_collection_handle().find_one(
                {"_id": identity}, projection, sort=sort, collation=collation
            )
        except BaseException:
            cache.discard_identity_admission(capture)
            raise
        cache.admit_identity(capture, read_shape, document, codec_options=codec_options)
        return document

    def _match_unique_key(
        self, filter_query: object, effective_collation: Mapping[str, Any] | None
    ) -> tuple[UniqueKeyDefinition, tuple[Any, ...]] | None:
        keys = self._database.manager._unique_keys_for(  # noqa: SLF001
            self._namespace(), self._list_indexes_probe
        )
        if not keys:
            return None
        return match_unique_key(filter_query, keys, effective_collation)

    def _find_one_by_unique_key(
        self,
        key_definition: UniqueKeyDefinition,
        key_values: tuple[Any, ...],
        original_filter: Mapping[str, Any],
        projection: Mapping[str, Any] | Sequence[str] | None,
        read_shape: object,
        *,
        sort: Sequence[tuple[str, int]] | None,
        collation: _CollationIn | None,
    ) -> DocumentType | None:
        namespace = self._namespace()
        cache = self._database.manager.cache_core
        codec_options = self._collection.codec_options
        alias = canonical_alias_key(
            key_definition.fields, key_values, key_definition.collation
        )
        discriminator = (alias, read_shape)

        resolved_identity = cache.resolve_alias(
            namespace, key_definition.fields, key_values, key_definition.collation
        )
        if resolved_identity is not None:
            lookup_result = cache.lookup_identity(
                namespace, resolved_identity, read_shape, codec_options=codec_options
            )
            if lookup_result.hit:
                return cast("DocumentType | None", lookup_result.value)
            if not cache.is_database_available(namespace.database):
                return self._collection.find_one(
                    original_filter, projection, sort=sort, collation=collation
                )
            return self._resolve_unique_key_read(
                alias,
                discriminator,
                original_filter,
                projection,
                read_shape,
                sort=sort,
                collation=collation,
                previous_identity=resolved_identity,
            )

        lookup_result = cache.lookup_namespace(
            namespace, discriminator, codec_options=codec_options
        )
        if lookup_result.hit:
            return cast("DocumentType | None", lookup_result.value)
        if not cache.is_database_available(namespace.database):
            return self._collection.find_one(
                original_filter, projection, sort=sort, collation=collation
            )
        return self._resolve_unique_key_read(
            alias,
            discriminator,
            original_filter,
            projection,
            read_shape,
            sort=sort,
            collation=collation,
        )

    def _resolve_unique_key_read(
        self,
        alias: AliasKey,
        discriminator: object,
        original_filter: Mapping[str, Any],
        projection: Mapping[str, Any] | Sequence[str] | None,
        read_shape: object,
        *,
        sort: Sequence[tuple[str, int]] | None,
        collation: _CollationIn | None,
        previous_identity: object | None = None,
    ) -> DocumentType | None:
        namespace = self._namespace()
        cache = self._database.manager.cache_core
        codec_options = self._collection.codec_options
        capture = cache.capture_namespace_generation(namespace)
        server_projection, exclude_id = ensure_id_present_for_resolution(projection)
        document = self._forced_collection_handle().find_one(
            original_filter, server_projection, sort=sort, collation=collation
        )
        if document is None:
            if previous_identity is not None:
                cache.discard_stale_alias(namespace, alias, previous_identity)
            cache.discard_namespace_entry(namespace, discriminator, capture.generation)
            cache.admit_namespace(
                capture, discriminator, None, codec_options=codec_options
            )
            return None
        raw_identity = document["_id"]
        if exclude_id:
            document = cast("DocumentType", without_id(document, codec_options))
        cache_identity = normalize_identity_for_cache_key(
            raw_identity, codec_options, self._database.manager.client.codec_options
        )
        if cache_identity is not None and is_canonicalizable(cache_identity):
            cache.discard_namespace_entry(namespace, discriminator, capture.generation)
            outcome = cache.admit_unique_key_match(
                capture,
                discriminator,
                cache_identity,
                read_shape,
                document,
                alias=alias,
                codec_options=codec_options,
            )
            if (
                outcome is not AdmissionOutcome.ADMITTED
                and previous_identity is not None
            ):
                cache.discard_stale_alias(namespace, alias, previous_identity)
        elif previous_identity is not None:
            cache.discard_stale_alias(namespace, alias, previous_identity)
            cache.discard_namespace_entry(namespace, discriminator, capture.generation)
        return document

    def _namespace(self) -> NamespaceId:
        return NamespaceId(self._database.name, self.name)

    def _request_bypass_reason(
        self, *, session: ClientSession | None, kwargs: Mapping[str, object]
    ) -> BypassReason | None:
        return request_bypass_reason(
            session,
            self._collection.read_preference,
            self._collection.read_concern.level,
            kwargs,
            bound_session=getattr(
                self._collection.database.client, "_get_bound_session", None
            ),
        )

    def _record_bypass(self, reason: BypassReason) -> None:
        self._database.manager.cache_core.record_bypass(reason)

    def _forced_collection_handle(self) -> Collection[DocumentType]:
        if self._forced_collection is None:
            self._forced_collection = self._collection.with_options(
                read_preference=ReadPreference.PRIMARY,
                read_concern=_FORCED_READ_CONCERN,
            )
        return self._forced_collection

    def _forced_database_handle(self) -> Database[DocumentType]:
        if self._forced_database is None:
            self._forced_database = self._database.raw.with_options(
                read_preference=ReadPreference.PRIMARY,
                read_concern=_FORCED_READ_CONCERN,
            )
        return self._forced_database

    def _cache_ineligibility_reason(self) -> BypassReason | None:
        return self._database.manager._cache_ineligibility_reason(  # noqa: SLF001
            self._namespace(), self._probe_collection
        )

    def _probe_collection(self) -> CollectionProbeResult | None:
        try:
            entry = next(
                iter(
                    self._forced_database_handle().list_collections(
                        filter={"name": self.name}
                    )
                ),
                None,
            )
        except PyMongoError:
            logger.warning(
                "collection-type probe failed; this read bypasses the cache",
                extra={"database": self._database.name, "collection": self.name},
                exc_info=True,
            )
            return None
        return interpret_list_collections_entry(entry)

    def _list_indexes_probe(self) -> list[Mapping[str, Any]] | None:
        try:
            return list(self._forced_collection_handle().list_indexes())
        except PyMongoError:
            logger.warning(
                "index metadata probe failed; unique-key discovery is skipped for "
                "this read",
                extra={"database": self._database.name, "collection": self.name},
                exc_info=True,
            )
            return None
