from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, cast

from pymongo import ReadPreference
from pymongo.collation import Collation
from pymongo.cursor import CursorType
from pymongo.errors import PyMongoError
from pymongo.read_concern import ReadConcern

from mongo_client_cache._core.canonical import is_canonicalizable
from mongo_client_cache._core.codec import codec_fingerprint
from mongo_client_cache._core.collection_metadata import (
    interpret_list_collections_entry,
)
from mongo_client_cache._core.errors import UnsupportedCacheRequestError
from mongo_client_cache._core.identity_reads import (
    NO_IDENTITY,
    extract_id_identity,
    normalize_identity_for_cache_key,
)
from mongo_client_cache._core.keys import NamespaceId, canonical_alias_key
from mongo_client_cache._core.order_sensitive_keys import (
    order_sensitive_discriminator_key,
)
from mongo_client_cache._core.projection import (
    ensure_id_present_for_resolution,
    without_id,
)
from mongo_client_cache._core.read_validation import (
    is_filter_cacheable,
    is_pipeline_cacheable,
    is_projection_cacheable,
    pipeline_blocks_full_materialization,
)
from mongo_client_cache._core.unique_keys import match_unique_key

if TYPE_CHECKING:
    from pymongo.client_session import ClientSession
    from pymongo.synchronous.collection import Collection
    from pymongo.synchronous.database import Database

    from mongo_client_cache._core.collection_metadata import CollectionProbeResult
    from mongo_client_cache._core.keys import AliasKey
    from mongo_client_cache._core.unique_keys import UniqueKeyDefinition
    from mongo_client_cache.synchronous.database import CachedDatabase

_FORCED_READ_CONCERN = ReadConcern("majority")
_ACCEPTABLE_READ_CONCERN_LEVELS = (None, "majority")

logger = logging.getLogger(__name__)

type _CollationIn = Collation | Mapping[str, Any]


def _collation_document(collation: _CollationIn | None) -> Mapping[str, Any] | None:
    if collation is None:
        return None
    if isinstance(collation, Collation):
        return collation.document
    return dict(collation)


def _blocks_full_materialization(kwargs: Mapping[str, object]) -> bool:
    cursor_type = kwargs.get("cursor_type", CursorType.NON_TAILABLE)
    if cursor_type != CursorType.NON_TAILABLE:
        return True
    return bool(kwargs.get("allow_partial_results", False))


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
    __slots__ = ("_collection", "_database", "_forced_collection", "_forced_database")

    def __init__(
        self,
        database: CachedDatabase[DocumentType],
        collection: Collection[DocumentType],
    ) -> None:
        self._database = database
        self._collection = collection
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

    def find_one(
        self,
        filter: object = None,  # noqa: A002
        projection: Mapping[str, Any] | Sequence[str] | None = None,
        *,
        session: ClientSession | None = None,
        **kwargs: object,
    ) -> DocumentType | None:
        identity = extract_id_identity(filter)
        codec_options = self._collection.codec_options
        read_shape = order_sensitive_discriminator_key(
            ("find_one", projection, codec_fingerprint(codec_options))
        )
        if (
            self._wants_bypass(session=session, kwargs=kwargs)
            or not is_projection_cacheable(projection)
            or not is_canonicalizable(read_shape)
            or not self._is_cache_eligible()
        ):
            self._record_bypass()
            return self._collection.find_one(
                filter, projection, session=session, **kwargs
            )
        if identity is not NO_IDENTITY:
            if not is_canonicalizable(identity):
                self._record_bypass()
                return self._collection.find_one(
                    filter, projection, session=session, **kwargs
                )
            return self._find_one_by_id(identity, projection, read_shape)
        unique_key_match = self._match_unique_key(filter)
        if unique_key_match is None:
            self._record_bypass()
            return self._collection.find_one(
                filter, projection, session=session, **kwargs
            )
        key_definition, key_values = unique_key_match
        return self._find_one_by_unique_key(
            key_definition,
            key_values,
            cast("Mapping[str, Any]", filter),
            projection,
            read_shape,
        )

    def find(
        self,
        filter: Mapping[str, Any] | None = None,  # noqa: A002
        projection: Mapping[str, Any] | Sequence[str] | None = None,
        *,
        sort: Sequence[tuple[str, int]] | None = None,
        skip: int = 0,
        limit: int = 0,
        collation: _CollationIn | None = None,
        session: ClientSession | None = None,
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
            or not self._is_cache_eligible()
        ):
            self._record_bypass()
            return list(
                self._collection.find(
                    filter,
                    projection,
                    skip=skip,
                    limit=limit,
                    sort=sort,
                    collation=collation,
                    session=session,
                    **kwargs,
                )
            )
        namespace = self._namespace()
        cache = self._database.manager.cache_core
        lookup_result = cache.lookup_namespace(
            namespace, discriminator, codec_options=codec_options
        )
        if lookup_result.hit:
            return cast("list[DocumentType]", lookup_result.value)
        if not cache.is_database_available(namespace.database):
            return list(
                self._collection.find(
                    filter,
                    projection,
                    skip=skip,
                    limit=limit,
                    sort=sort,
                    collation=collation,
                    session=session,
                    **kwargs,
                )
            )
        capture = cache.capture_namespace_generation(namespace)
        documents = list(
            self._forced_collection_handle().find(
                filter,
                projection,
                skip=skip,
                limit=limit,
                sort=sort,
                collation=collation,
            )
        )
        cache.admit_namespace(
            capture, discriminator, documents, codec_options=codec_options
        )
        return documents

    def aggregate(
        self,
        pipeline: Sequence[Mapping[str, Any]],
        *,
        collation: _CollationIn | None = None,
        session: ClientSession | None = None,
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
            or not self._is_cache_eligible()
        ):
            self._record_bypass()
            return list(
                self._collection.aggregate(
                    pipeline,
                    collation=collation,
                    session=session,
                    **cast("dict[str, Any]", kwargs),
                )
            )
        namespace = self._namespace()
        cache = self._database.manager.cache_core
        lookup_result = cache.lookup_namespace(
            namespace, discriminator, codec_options=codec_options
        )
        if lookup_result.hit:
            return cast("list[DocumentType]", lookup_result.value)
        if not cache.is_database_available(namespace.database):
            return list(
                self._collection.aggregate(
                    pipeline,
                    collation=collation,
                    session=session,
                    **cast("dict[str, Any]", kwargs),
                )
            )
        capture = cache.capture_namespace_generation(namespace)
        documents = list(
            self._forced_collection_handle().aggregate(pipeline, collation=collation)
        )
        cache.admit_namespace(
            capture, discriminator, documents, codec_options=codec_options
        )
        return documents

    def count_documents(
        self,
        filter: Mapping[str, Any],  # noqa: A002
        *,
        skip: int = 0,
        limit: int = 0,
        collation: _CollationIn | None = None,
        hint: str | Sequence[tuple[str, int]] | None = None,
        session: ClientSession | None = None,
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
            or not self._is_cache_eligible()
        ):
            self._record_bypass()
            return self._collection.count_documents(
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
            return self._collection.count_documents(
                filter, session=session, **merged_kwargs
            )
        capture = cache.capture_namespace_generation(namespace)
        count = self._forced_collection_handle().count_documents(
            filter, **merged_kwargs
        )
        cache.admit_namespace(
            capture, discriminator, count, codec_options=codec_options
        )
        return count

    def estimated_document_count(self, **kwargs: object) -> int:
        if kwargs or not self._is_primary_majority() or not self._is_cache_eligible():
            self._record_bypass()
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
                _collation_document(collation),
                codec_fingerprint(codec_options),
            )
        )
        if (
            self._wants_bypass(session=session, kwargs=kwargs)
            or not is_filter_cacheable(filter)
            or not is_canonicalizable(discriminator)
            or not self._is_cache_eligible()
        ):
            self._record_bypass()
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
    ) -> DocumentType | None:
        namespace = self._namespace()
        cache = self._database.manager.cache_core
        codec_options = self._collection.codec_options
        cache_identity = normalize_identity_for_cache_key(
            identity, codec_options, self._database.manager.client.codec_options
        )
        if not is_canonicalizable(cache_identity):
            self._record_bypass()
            return self._collection.find_one({"_id": identity}, projection)
        lookup_result = cache.lookup_identity(
            namespace, cache_identity, read_shape, codec_options=codec_options
        )
        if lookup_result.hit:
            return cast("DocumentType | None", lookup_result.value)
        if not cache.is_database_available(namespace.database):
            return self._collection.find_one({"_id": identity}, projection)
        capture = cache.begin_identity_admission(namespace, cache_identity)
        try:
            document = self._forced_collection_handle().find_one(
                {"_id": identity}, projection
            )
        except BaseException:
            cache.discard_identity_admission(capture)
            raise
        cache.admit_identity(capture, read_shape, document, codec_options=codec_options)
        return document

    def _match_unique_key(
        self, filter_query: object
    ) -> tuple[UniqueKeyDefinition, tuple[Any, ...]] | None:
        namespace = self._namespace()
        manager = self._database.manager
        keys = manager.unique_keys_for(namespace, self._list_indexes_probe)
        if not keys:
            return None
        default_collation = manager.default_collation_for(namespace)
        return match_unique_key(filter_query, keys, default_collation)

    def _find_one_by_unique_key(
        self,
        key_definition: UniqueKeyDefinition,
        key_values: tuple[Any, ...],
        original_filter: Mapping[str, Any],
        projection: Mapping[str, Any] | Sequence[str] | None,
        read_shape: object,
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
                return self._collection.find_one(original_filter, projection)
            return self._resolve_unique_key_read(
                alias,
                discriminator,
                original_filter,
                projection,
                read_shape,
                previous_identity=resolved_identity,
            )

        lookup_result = cache.lookup_namespace(
            namespace, discriminator, codec_options=codec_options
        )
        if lookup_result.hit:
            return cast("DocumentType | None", lookup_result.value)
        if not cache.is_database_available(namespace.database):
            return self._collection.find_one(original_filter, projection)
        return self._resolve_unique_key_read(
            alias, discriminator, original_filter, projection, read_shape
        )

    def _resolve_unique_key_read(
        self,
        alias: AliasKey,
        discriminator: object,
        original_filter: Mapping[str, Any],
        projection: Mapping[str, Any] | Sequence[str] | None,
        read_shape: object,
        *,
        previous_identity: object | None = None,
    ) -> DocumentType | None:
        namespace = self._namespace()
        cache = self._database.manager.cache_core
        codec_options = self._collection.codec_options
        capture = cache.capture_namespace_generation(namespace)
        server_projection, exclude_id = ensure_id_present_for_resolution(projection)
        document = self._forced_collection_handle().find_one(
            original_filter, server_projection
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
            document = cast("DocumentType", without_id(document))
        cache_identity = normalize_identity_for_cache_key(
            raw_identity, codec_options, self._database.manager.client.codec_options
        )
        if is_canonicalizable(cache_identity):
            cache.discard_namespace_entry(namespace, discriminator, capture.generation)
            cache.admit_unique_key_match(
                capture,
                discriminator,
                cache_identity,
                read_shape,
                document,
                alias=alias,
                codec_options=codec_options,
            )
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
        self, *, session: ClientSession | None, kwargs: Mapping[str, object]
    ) -> bool:
        return session is not None or bool(kwargs) or not self._is_primary_majority()

    def _record_bypass(self) -> None:
        self._database.manager.cache_core.record_bypass()

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

    def _is_cache_eligible(self) -> bool:
        return self._database.manager.ensure_cache_eligible(
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
