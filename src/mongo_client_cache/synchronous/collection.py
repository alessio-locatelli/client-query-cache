from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, cast

from pymongo import ReadPreference
from pymongo.collation import Collation
from pymongo.cursor import CursorType
from pymongo.errors import PyMongoError
from pymongo.read_concern import ReadConcern

from mongo_client_cache._core.canonical import is_canonicalizable
from mongo_client_cache._core.collection_metadata import (
    interpret_list_collections_entry,
)
from mongo_client_cache._core.errors import UnsupportedCacheRequestError
from mongo_client_cache._core.identity_reads import (
    NO_IDENTITY,
    extract_id_identity,
    normalize_identity_for_cache_key,
)
from mongo_client_cache._core.keys import NamespaceId
from mongo_client_cache._core.order_sensitive_keys import (
    order_sensitive_discriminator_key,
)
from mongo_client_cache._core.read_validation import (
    is_filter_cacheable,
    is_pipeline_cacheable,
    pipeline_blocks_full_materialization,
)

if TYPE_CHECKING:
    from pymongo.client_session import ClientSession
    from pymongo.synchronous.collection import Collection

    from mongo_client_cache.synchronous.database import CachedDatabase

_FORCED_READ_CONCERN = ReadConcern("majority")
_ACCEPTABLE_READ_CONCERN_LEVELS = (None, "majority")

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
    __slots__ = ("_collection", "_database", "_forced_collection")

    def __init__(
        self,
        database: CachedDatabase[DocumentType],
        collection: Collection[DocumentType],
    ) -> None:
        self._database = database
        self._collection = collection
        self._forced_collection: Collection[DocumentType] | None = None

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
        read_shape = ("find_one", order_sensitive_discriminator_key(projection))
        if (
            identity is NO_IDENTITY
            or self._wants_bypass(session=session, kwargs=kwargs)
            or not is_canonicalizable(identity)
            or not is_canonicalizable(read_shape)
            or not self._is_cache_eligible()
        ):
            return self._collection.find_one(
                filter, projection, session=session, **kwargs
            )
        return self._find_one_by_id(identity, projection, read_shape)

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
        discriminator = order_sensitive_discriminator_key(
            (
                "find",
                filter,
                projection,
                sort,
                skip,
                limit,
                _collation_document(collation),
            )
        )
        if (
            self._wants_bypass(session=session, kwargs=kwargs)
            or not is_filter_cacheable(filter)
            or not is_canonicalizable(discriminator)
            or not self._is_cache_eligible()
        ):
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
        codec_options = self._collection.codec_options
        lookup_result = cache.lookup_namespace(
            namespace, discriminator, codec_options=codec_options
        )
        if lookup_result.hit:
            return cast("list[DocumentType]", lookup_result.value)
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
        discriminator = order_sensitive_discriminator_key(
            ("aggregate", pipeline, _collation_document(collation))
        )
        if (
            self._wants_bypass(session=session, kwargs=kwargs)
            or not is_pipeline_cacheable(pipeline)
            or not is_canonicalizable(discriminator)
            or not self._is_cache_eligible()
        ):
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
        codec_options = self._collection.codec_options
        lookup_result = cache.lookup_namespace(
            namespace, discriminator, codec_options=codec_options
        )
        if lookup_result.hit:
            return cast("list[DocumentType]", lookup_result.value)
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
        discriminator = order_sensitive_discriminator_key(
            (
                "count_documents",
                filter,
                skip,
                limit,
                _collation_document(collation),
                hint,
            )
        )
        if (
            self._wants_bypass(session=session, kwargs=kwargs)
            or not is_filter_cacheable(filter)
            or not is_canonicalizable(discriminator)
            or not self._is_cache_eligible()
        ):
            return self._collection.count_documents(
                filter, session=session, **merged_kwargs
            )
        namespace = self._namespace()
        cache = self._database.manager.cache_core
        codec_options = self._collection.codec_options
        lookup_result = cache.lookup_namespace(
            namespace, discriminator, codec_options=codec_options
        )
        if lookup_result.hit:
            return cast("int", lookup_result.value)
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
        discriminator = order_sensitive_discriminator_key(
            ("distinct", key, filter, _collation_document(collation))
        )
        if (
            self._wants_bypass(session=session, kwargs=kwargs)
            or not is_filter_cacheable(filter)
            or not is_canonicalizable(discriminator)
            or not self._is_cache_eligible()
        ):
            return self._collection.distinct(
                key,
                filter,
                collation=collation,
                session=session,
                **cast("dict[str, Any]", kwargs),
            )
        namespace = self._namespace()
        cache = self._database.manager.cache_core
        codec_options = self._collection.codec_options
        lookup_result = cache.lookup_namespace(
            namespace, discriminator, codec_options=codec_options
        )
        if lookup_result.hit:
            return cast("list[Any]", lookup_result.value)
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
        lookup_result = cache.lookup_identity(
            namespace, cache_identity, read_shape, codec_options=codec_options
        )
        if lookup_result.hit:
            return cast("DocumentType | None", lookup_result.value)
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

    def _forced_collection_handle(self) -> Collection[DocumentType]:
        if self._forced_collection is None:
            self._forced_collection = self._collection.with_options(
                read_preference=ReadPreference.PRIMARY,
                read_concern=_FORCED_READ_CONCERN,
            )
        return self._forced_collection

    def _is_cache_eligible(self) -> bool:
        return self._database.manager.ensure_cache_eligible(
            self._namespace(), self._check_is_view
        )

    def _check_is_view(self) -> bool | None:
        try:
            entry = next(
                iter(self._database.raw.list_collections(filter={"name": self.name})),
                None,
            )
        except PyMongoError:
            return None
        return interpret_list_collections_entry(entry)
