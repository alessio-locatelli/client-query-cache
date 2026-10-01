from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, cast

from pymongo import ReadPreference
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.collation import Collation
from pymongo.cursor import CursorType
from pymongo.errors import PyMongoError
from pymongo.read_concern import ReadConcern

from client_query_cache._core.canonical import canonicalize, is_canonicalizable
from client_query_cache._core.codec import codec_fingerprint
from client_query_cache._core.collection_metadata import (
    interpret_list_collections_entry,
)
from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.errors import UnsupportedCacheRequestError
from client_query_cache._core.find_one_reads import (
    effective_find_one_collation,
    find_one_options_cacheable,
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
from client_query_cache._core.read_validation import (
    is_filter_cacheable,
    is_pipeline_cacheable,
    is_projection_cacheable,
    pipeline_blocks_full_materialization,
)
from client_query_cache._core.traversal import (
    declared_attribute_names,
    ensure_subcollection_name,
)
from client_query_cache._core.unique_keys import match_unique_key

if TYPE_CHECKING:
    from pymongo.asynchronous.client_session import AsyncClientSession
    from pymongo.asynchronous.database import AsyncDatabase

    from client_query_cache._core.collection_metadata import CollectionProbeResult
    from client_query_cache._core.keys import AliasKey
    from client_query_cache._core.unique_keys import UniqueKeyDefinition
    from client_query_cache.asynchronous.database import CachedDatabase

_FORCED_READ_CONCERN = ReadConcern("majority")
_ACCEPTABLE_READ_CONCERN_LEVELS = (None, "majority")
_COLLECTION_ATTRIBUTE_NAMES = declared_attribute_names(AsyncCollection)

logger = logging.getLogger(__name__)

type _CollationIn = Collation | Mapping[str, Any]


def _collation_document(collation: _CollationIn | None) -> Mapping[str, Any] | None:
    if collation is None:
        return None
    if isinstance(collation, Collation):
        return collation.document
    return dict(collation)


def _blocks_full_materialization(kwargs: Mapping[str, object]) -> bool:
    try:
        cursor_type = kwargs["cursor_type"]
    except KeyError:
        cursor_type = CursorType.NON_TAILABLE
    if cursor_type != CursorType.NON_TAILABLE:
        return True
    try:
        allow_partial_results = kwargs["allow_partial_results"]
    except KeyError:
        allow_partial_results = False
    return bool(allow_partial_results)


def _count_documents_kwargs(
    skip: int,
    limit: int,
    collation: _CollationIn | None,
    hint: str | Sequence[tuple[str, int]] | None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if skip:
        kwargs["skip"] = skip
    if limit:
        kwargs["limit"] = limit
    if collation is not None:
        kwargs["collation"] = collation
    if hint is not None:
        kwargs["hint"] = hint
    return kwargs


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
        collection: AsyncCollection[DocumentType],
    ) -> None:
        self._database = database
        self._collection = collection
        self._find_one_default_shape = find_one_read_shape(
            None, None, None, codec_fingerprint(collection.codec_options)
        )
        self._forced_collection: AsyncCollection[DocumentType] | None = None
        self._forced_database: AsyncDatabase[DocumentType] | None = None

    @property
    def database(self) -> CachedDatabase[DocumentType]:
        return self._database

    @property
    def name(self) -> str:
        return self._collection.name

    @property
    def raw(self) -> AsyncCollection[DocumentType]:
        return self._collection

    def __getitem__(self, name: str) -> CachedCollection[DocumentType]:
        return CachedCollection(self._database, self._collection[name])

    def __getattr__(self, name: str) -> CachedCollection[DocumentType]:
        ensure_subcollection_name(self, name, _COLLECTION_ATTRIBUTE_NAMES)
        return self[name]

    async def find_one(
        self,
        filter: object = None,  # noqa: A002
        projection: Mapping[str, Any] | Sequence[str] | None = None,
        *,
        sort: Sequence[tuple[str, int]] | None = None,
        collation: _CollationIn | None = None,
        session: AsyncClientSession | None = None,
        **kwargs: object,
    ) -> DocumentType | None:
        filter_query = normalize_find_one_filter(filter)
        if (
            self._wants_bypass(session=session, kwargs=kwargs)
            or not find_one_options_cacheable(filter_query, projection, sort, collation)
            or not await self._is_cache_eligible()
        ):
            self._record_bypass()
            return await self._collection.find_one(
                filter,
                projection,
                sort=sort,
                collation=collation,
                session=session,
                **kwargs,
            )
        effective_collation = effective_find_one_collation(
            collation, self._database.manager.default_collation_for(self._namespace())
        )
        codec_options = self._collection.codec_options
        try:
            read_shape = canonicalize(
                self._find_one_default_shape
                if projection is None and sort is None and effective_collation is None
                else find_one_read_shape(
                    projection,
                    sort,
                    effective_collation,
                    codec_fingerprint(codec_options),
                )
            )
        except UnsupportedCacheRequestError:
            self._record_bypass()
            return await self._collection.find_one(
                filter, projection, sort=sort, collation=collation, session=session
            )
        identity = extract_id_identity(filter)
        if identity is not NO_IDENTITY and effective_collation is None:
            if is_canonicalizable(identity):
                return await self._find_one_by_id(
                    identity, projection, read_shape, sort=sort, collation=collation
                )
            self._record_bypass()
            return await self._collection.find_one(
                filter, projection, sort=sort, collation=collation, session=session
            )
        namespace = self._namespace()
        cache = self._database.manager.cache_core
        known_keys = await self._database.manager.unique_keys_for(namespace)
        unique_key_match = (
            match_unique_key(filter_query, known_keys, effective_collation)
            if identity is NO_IDENTITY and known_keys is not None
            else None
        )
        if unique_key_match is None:
            try:
                discriminator = canonicalize(
                    generic_find_one_discriminator(
                        filter_query,
                        read_shape,
                        cache.current_index_generation(namespace),
                    )
                )
            except UnsupportedCacheRequestError:
                self._record_bypass()
                return await self._collection.find_one(
                    filter, projection, sort=sort, collation=collation, session=session
                )
            lookup_result = cache.lookup_namespace(
                namespace, discriminator, codec_options=codec_options
            )
            if lookup_result.hit:
                return cast("DocumentType | None", lookup_result.value)
            if identity is NO_IDENTITY and known_keys is None:
                unique_key_match = await self._match_unique_key(
                    filter_query, effective_collation
                )
        if unique_key_match is not None:
            key_definition, key_values = unique_key_match
            return await self._find_one_by_unique_key(
                key_definition,
                key_values,
                filter_query,
                projection,
                read_shape,
                sort=sort,
                collation=collation,
            )
        if not cache.is_database_available(namespace.database):
            return await self._collection.find_one(
                filter, projection, sort=sort, collation=collation, session=session
            )
        capture = cache.capture_namespace_generation(namespace)
        document = await self._forced_collection_handle().find_one(
            filter, projection, sort=sort, collation=collation
        )
        cache.admit_namespace(
            capture, discriminator, document, codec_options=codec_options
        )
        return document

    async def find(
        self,
        filter: Mapping[str, Any] | None = None,  # noqa: A002
        projection: Mapping[str, Any] | Sequence[str] | None = None,
        *,
        sort: Sequence[tuple[str, int]] | None = None,
        skip: int = 0,
        limit: int = 0,
        collation: _CollationIn | None = None,
        session: AsyncClientSession | None = None,
        **kwargs: object,
    ) -> list[DocumentType]:
        if kwargs and _blocks_full_materialization(kwargs):
            message = (
                "find() always fully materializes its result and cannot support a "
                "tailable, exhaust, or partial-result cursor; use .raw.find() instead"
            )
            raise UnsupportedCacheRequestError(message)
        codec_options = self._collection.codec_options
        discriminator = order_sensitive_discriminator_key(
            (
                "find",
                filter,
                projection,
                sort,
                skip,
                limit,
                _collation_document(collation),
                codec_fingerprint(codec_options),
            )
        )
        if (
            self._wants_bypass(session=session, kwargs=kwargs)
            or not is_filter_cacheable(filter)
            or not is_projection_cacheable(projection)
            or not is_canonicalizable(discriminator)
            or not await self._is_cache_eligible()
        ):
            self._record_bypass()
            cursor = self._collection.find(
                filter,
                projection,
                skip=skip,
                limit=limit,
                sort=sort,
                collation=collation,
                session=session,
                **kwargs,
            )
            return await cursor.to_list()
        namespace = self._namespace()
        cache = self._database.manager.cache_core
        lookup_result = cache.lookup_namespace(
            namespace, discriminator, codec_options=codec_options
        )
        if lookup_result.hit:
            return cast("list[DocumentType]", lookup_result.value)
        if not cache.is_database_available(namespace.database):
            cursor = self._collection.find(
                filter,
                projection,
                skip=skip,
                limit=limit,
                sort=sort,
                collation=collation,
                session=session,
                **kwargs,
            )
            return await cursor.to_list()
        capture = cache.capture_namespace_generation(namespace)
        cursor = self._forced_collection_handle().find(
            filter,
            projection,
            skip=skip,
            limit=limit,
            sort=sort,
            collation=collation,
        )
        documents = await cursor.to_list()
        cache.admit_namespace(
            capture, discriminator, documents, codec_options=codec_options
        )
        return documents

    async def aggregate(
        self,
        pipeline: Sequence[Mapping[str, Any]],
        *,
        collation: _CollationIn | None = None,
        session: AsyncClientSession | None = None,
        **kwargs: object,
    ) -> list[DocumentType]:
        if pipeline_blocks_full_materialization(pipeline):
            message = (
                "aggregate() always fully materializes its result and cannot "
                "support a $changeStream pipeline; use .raw.aggregate() instead"
            )
            raise UnsupportedCacheRequestError(message)
        codec_options = self._collection.codec_options
        discriminator = order_sensitive_discriminator_key(
            (
                "aggregate",
                pipeline,
                _collation_document(collation),
                codec_fingerprint(codec_options),
            )
        )
        if (
            self._wants_bypass(session=session, kwargs=kwargs)
            or not is_pipeline_cacheable(pipeline)
            or not is_canonicalizable(discriminator)
            or not await self._is_cache_eligible()
        ):
            self._record_bypass()
            cursor = await self._collection.aggregate(
                pipeline,
                collation=collation,
                session=session,
                **cast("dict[str, Any]", kwargs),
            )
            return await cursor.to_list()
        namespace = self._namespace()
        cache = self._database.manager.cache_core
        lookup_result = cache.lookup_namespace(
            namespace, discriminator, codec_options=codec_options
        )
        if lookup_result.hit:
            return cast("list[DocumentType]", lookup_result.value)
        if not cache.is_database_available(namespace.database):
            cursor = await self._collection.aggregate(
                pipeline,
                collation=collation,
                session=session,
                **cast("dict[str, Any]", kwargs),
            )
            return await cursor.to_list()
        capture = cache.capture_namespace_generation(namespace)
        cursor = await self._forced_collection_handle().aggregate(
            pipeline, collation=collation
        )
        documents = await cursor.to_list()
        cache.admit_namespace(
            capture, discriminator, documents, codec_options=codec_options
        )
        return documents

    async def count_documents(
        self,
        filter: Mapping[str, Any],  # noqa: A002
        *,
        skip: int = 0,
        limit: int = 0,
        collation: _CollationIn | None = None,
        hint: str | Sequence[tuple[str, int]] | None = None,
        session: AsyncClientSession | None = None,
        **kwargs: object,
    ) -> int:
        merged_kwargs = _count_documents_kwargs(skip, limit, collation, hint) | kwargs
        codec_options = self._collection.codec_options
        discriminator = order_sensitive_discriminator_key(
            (
                "count_documents",
                filter,
                skip,
                limit,
                _collation_document(collation),
                hint,
                codec_fingerprint(codec_options),
            )
        )
        if (
            self._wants_bypass(session=session, kwargs=kwargs)
            or not is_filter_cacheable(filter)
            or not is_canonicalizable(discriminator)
            or not await self._is_cache_eligible()
        ):
            self._record_bypass()
            return await self._collection.count_documents(
                filter, session=session, **merged_kwargs
            )
        namespace = self._namespace()
        cache = self._database.manager.cache_core
        lookup_result = cache.lookup_namespace(
            namespace, discriminator, codec_options=codec_options
        )
        if lookup_result.hit:
            return cast("int", lookup_result.value)
        if not cache.is_database_available(namespace.database):
            return await self._collection.count_documents(
                filter, session=session, **merged_kwargs
            )
        capture = cache.capture_namespace_generation(namespace)
        count = await self._forced_collection_handle().count_documents(
            filter, **merged_kwargs
        )
        cache.admit_namespace(
            capture, discriminator, count, codec_options=codec_options
        )
        return count

    async def estimated_document_count(self, **kwargs: object) -> int:
        if (
            kwargs
            or not self._is_primary_majority()
            or not await self._is_cache_eligible()
        ):
            self._record_bypass()
            return await self._collection.estimated_document_count(**kwargs)
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
            return await self._collection.estimated_document_count()
        capture = cache.capture_namespace_generation(namespace)
        count = await self._forced_collection_handle().estimated_document_count()
        cache.admit_namespace(
            capture, discriminator, count, codec_options=codec_options
        )
        return count

    async def distinct(
        self,
        key: str,
        filter: Mapping[str, Any] | None = None,  # noqa: A002
        *,
        collation: _CollationIn | None = None,
        session: AsyncClientSession | None = None,
        **kwargs: object,
    ) -> list[Any]:
        codec_options = self._collection.codec_options
        discriminator = order_sensitive_discriminator_key(
            (
                "distinct",
                key,
                filter,
                _collation_document(collation),
                codec_fingerprint(codec_options),
            )
        )
        if (
            self._wants_bypass(session=session, kwargs=kwargs)
            or not is_filter_cacheable(filter)
            or not is_canonicalizable(discriminator)
            or not await self._is_cache_eligible()
        ):
            self._record_bypass()
            return await self._collection.distinct(
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
            return await self._collection.distinct(
                key,
                filter,
                collation=collation,
                session=session,
                **cast("dict[str, Any]", kwargs),
            )
        capture = cache.capture_namespace_generation(namespace)
        values = await self._forced_collection_handle().distinct(
            key, filter, collation=collation
        )
        cache.admit_namespace(
            capture, discriminator, values, codec_options=codec_options
        )
        return values

    async def _find_one_by_id(
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
            self._record_bypass()
            return await self._collection.find_one(
                {"_id": identity}, projection, sort=sort, collation=collation
            )
        lookup_result = cache.lookup_identity(
            namespace, cache_identity, read_shape, codec_options=codec_options
        )
        if lookup_result.hit:
            return cast("DocumentType | None", lookup_result.value)
        if not cache.is_database_available(namespace.database):
            return await self._collection.find_one(
                {"_id": identity}, projection, sort=sort, collation=collation
            )
        capture = cache.begin_identity_admission(namespace, cache_identity)
        try:
            document = await self._forced_collection_handle().find_one(
                {"_id": identity}, projection, sort=sort, collation=collation
            )
        except BaseException:
            cache.discard_identity_admission(capture)
            raise
        cache.admit_identity(capture, read_shape, document, codec_options=codec_options)
        return document

    async def _match_unique_key(
        self, filter_query: object, effective_collation: Mapping[str, Any] | None
    ) -> tuple[UniqueKeyDefinition, tuple[Any, ...]] | None:
        keys = await self._database.manager.unique_keys_for(
            self._namespace(), self._list_indexes_probe
        )
        if not keys:
            return None
        return match_unique_key(filter_query, keys, effective_collation)

    async def _find_one_by_unique_key(
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
                return await self._collection.find_one(
                    original_filter, projection, sort=sort, collation=collation
                )
            return await self._resolve_unique_key_read(
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
            return await self._collection.find_one(
                original_filter, projection, sort=sort, collation=collation
            )
        return await self._resolve_unique_key_read(
            alias,
            discriminator,
            original_filter,
            projection,
            read_shape,
            sort=sort,
            collation=collation,
        )

    async def _resolve_unique_key_read(
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
        document = await self._forced_collection_handle().find_one(
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

    def _is_primary_majority(self) -> bool:
        read_concern = self._collection.read_concern
        return (
            self._collection.read_preference == ReadPreference.PRIMARY
            and read_concern.level in _ACCEPTABLE_READ_CONCERN_LEVELS
        )

    def _wants_bypass(
        self, *, session: AsyncClientSession | None, kwargs: Mapping[str, object]
    ) -> bool:
        return session is not None or bool(kwargs) or not self._is_primary_majority()

    def _record_bypass(self) -> None:
        self._database.manager.cache_core.record_bypass()

    def _forced_collection_handle(self) -> AsyncCollection[DocumentType]:
        if self._forced_collection is None:
            self._forced_collection = self._collection.with_options(
                read_preference=ReadPreference.PRIMARY,
                read_concern=_FORCED_READ_CONCERN,
            )
        return self._forced_collection

    def _forced_database_handle(self) -> AsyncDatabase[DocumentType]:
        if self._forced_database is None:
            self._forced_database = self._database.raw.with_options(
                read_preference=ReadPreference.PRIMARY,
                read_concern=_FORCED_READ_CONCERN,
            )
        return self._forced_database

    async def _is_cache_eligible(self) -> bool:
        return await self._database.manager.ensure_cache_eligible(
            self._namespace(), self._probe_collection
        )

    async def _probe_collection(self) -> CollectionProbeResult | None:
        try:
            cursor = await self._forced_database_handle().list_collections(
                filter={"name": self.name}
            )
            entries = await cursor.to_list(length=1)
        except PyMongoError:
            logger.warning(
                "collection-type probe failed; this read bypasses the cache",
                extra={"database": self._database.name, "collection": self.name},
                exc_info=True,
            )
            return None
        entry = entries[0] if entries else None
        return interpret_list_collections_entry(entry)

    async def _list_indexes_probe(self) -> list[Mapping[str, Any]] | None:
        try:
            cursor = await self._forced_collection_handle().list_indexes()
            return cast("list[Mapping[str, Any]]", await cursor.to_list())
        except PyMongoError:
            logger.warning(
                "index metadata probe failed; unique-key discovery is skipped for "
                "this read",
                extra={"database": self._database.name, "collection": self.name},
                exc_info=True,
            )
            return None
