from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from bson import BSON, ObjectId
from bson.int64 import Int64
from pymongo.collation import Collation
from pymongo.database_shared import _check_name  # noqa: PLC2701 - Match PyMongo validation without allocating a database handle.
from pymongo.errors import InvalidName

from client_query_cache._core.collation import collation_document, normalize_collation
from client_query_cache._core.errors import CacheConfigurationError
from client_query_cache._core.order_sensitive_keys import canonical_order_sensitive_key
from client_query_cache._types import NonEmptyStr

if TYPE_CHECKING:
    from client_query_cache._core.collection_metadata import CollectionMetadata
    from client_query_cache._core.contracts import LocalCacheCore, NamespaceCaptureView
    from client_query_cache._core.keys import NamespaceId

MAX_PROOF_PATHS = 32
MAX_PROOF_BYTES = 64
MAX_PARTITION_WIRE_BYTES = MAX_PROOF_BYTES + 17
_PARTITION_SCALAR_TYPES = frozenset((int, Int64, bool, str, ObjectId))


@dataclass(frozen=True, slots=True)
class SelectiveInvalidation:
    insert_partition_field: NonEmptyStr | None = None
    update_dependencies_for_counts: bool = False

    def __post_init__(self) -> None:
        field = self.insert_partition_field
        if field is not None and (
            not isinstance(field, str)
            or not field
            or field.startswith("$")
            or any(character in field for character in (".", "\0"))
        ):
            raise CacheConfigurationError(
                "insert_partition_field must be a nonempty top-level field name "
                "without dots, a leading '$', or NUL"
            )
        if type(self.update_dependencies_for_counts) is not bool:
            raise CacheConfigurationError(
                "update_dependencies_for_counts must be a built-in boolean"
            )


type CollectionPolicies = Mapping[str, SelectiveInvalidation]
type DatabasePolicies = Mapping[str, CollectionPolicies]


EMPTY_POLICIES: DatabasePolicies = MappingProxyType({})


def normalize_invalidation(
    invalidation: Mapping[tuple[str, str], SelectiveInvalidation] | None,
) -> DatabasePolicies:
    if invalidation is None:
        return EMPTY_POLICIES
    if not isinstance(invalidation, Mapping):
        raise CacheConfigurationError(
            "invalidation must be a namespace-to-policy mapping"
        )
    databases: dict[str, dict[str, SelectiveInvalidation]] = {}
    for namespace, policy in invalidation.items():
        if (
            not isinstance(namespace, tuple)
            or len(namespace) != 2
            or not all(isinstance(name, str) and name for name in namespace)
        ):
            raise CacheConfigurationError(
                "invalidation keys must be (database, collection) name pairs"
            )
        database, collection = namespace
        try:
            _check_name(database)
        except InvalidName as error:
            raise CacheConfigurationError(str(error)) from error
        if (
            any(part in collection for part in ("\0", ".."))
            or collection[:1] == "."
            or collection[-1:] == "."
            or ("$" in collection and collection not in {"oplog.$main", "$cmd"})
        ):
            raise CacheConfigurationError("invalid collection name in invalidation")
        if not isinstance(policy, SelectiveInvalidation):
            raise CacheConfigurationError(
                "invalidation values must be SelectiveInvalidation"
            )
        if (
            policy.insert_partition_field is None
            and not policy.update_dependencies_for_counts
        ):
            continue
        try:
            collections = databases[database]
        except KeyError:
            collections = {}
            databases[database] = collections
        collections[collection] = policy
    if not databases:
        return EMPTY_POLICIES
    return MappingProxyType(
        {
            database: MappingProxyType(collections)
            for database, collections in databases.items()
        }
    )


def collection_policy(
    policies: DatabasePolicies | None, namespace: NamespaceId
) -> SelectiveInvalidation | None:
    if policies is None:
        return None
    try:
        return policies[namespace.database][namespace.collection]
    except KeyError:
        return None


def partition_scalar(value: object) -> bytes | None:
    if type(value) not in _PARTITION_SCALAR_TYPES:
        return None
    if isinstance(value, str) and len(value) > MAX_PROOF_BYTES:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        if not -(2**63) <= value < 2**63:
            return None
        canonical = canonical_order_sensitive_key(value)
        assert isinstance(canonical, int)
        value = int(canonical)
    encoded = BSON.encode({"value": value})
    return encoded if len(encoded) <= MAX_PARTITION_WIRE_BYTES else None


def partition_proof(filter_document: object, field: str) -> bytes | None:
    if not isinstance(filter_document, Mapping):
        return None
    partition = None
    for name, predicate in filter_document.items():
        if name == "$and":
            if not isinstance(predicate, (list, tuple)) or not predicate:
                return None
            for conjunct in predicate:
                proof = partition_proof(conjunct, field)
                if proof is not None:
                    if partition is not None and partition != proof:
                        return None
                    partition = proof
                elif _mentions_partition(conjunct, field):
                    return None
        elif name == field:
            if isinstance(predicate, Mapping):
                if tuple(predicate) != ("$eq",):
                    return None
                value = predicate["$eq"]
            else:
                value = predicate
            proof = partition_scalar(value)
            if proof is None or (partition is not None and partition != proof):
                return None
            partition = proof
        elif (isinstance(name, str) and name.startswith(field + ".")) or (
            isinstance(name, str)
            and name.startswith("$")
            and _mentions_partition({name: predicate}, field)
        ):
            return None
    return partition


def _mentions_partition(predicate: object, field: str) -> bool:
    if not isinstance(predicate, Mapping):
        return True
    for name, value in predicate.items():
        if name == field or (isinstance(name, str) and name.startswith(field + ".")):
            return True
        if name in {"$and", "$or", "$nor"}:
            if not isinstance(value, (list, tuple)) or not value:
                return True
            if any(_mentions_partition(conjunct, field) for conjunct in value):
                return True
        elif isinstance(name, str) and name.startswith("$"):
            return True
    return False


def valid_dependency_path(path: object) -> bool:
    return (
        isinstance(path, str)
        and len(path.encode("utf-8")) <= MAX_PROOF_BYTES
        and all(
            part
            and not part.startswith("$")
            and not part.isdecimal()
            and "\0" not in part
            for part in path.split(".")
        )
    )


def count_dependencies(filter_document: object) -> tuple[str, ...] | None:
    if not isinstance(filter_document, Mapping):
        return None
    dependencies: set[str] = set()
    pending = [filter_document]
    while pending:
        document = pending.pop()
        for name, predicate in document.items():
            if name in {"$and", "$or", "$nor"}:
                if not isinstance(predicate, (list, tuple)) or not predicate:
                    return None
                for conjunct in predicate:
                    if not isinstance(conjunct, Mapping):
                        return None
                    pending.append(conjunct)
            else:
                if not valid_dependency_path(name):
                    return None
                if (
                    isinstance(predicate, Mapping)
                    and any(
                        isinstance(operator, str) and operator.startswith("$")
                        for operator in predicate
                    )
                    and (
                        any(
                            operator
                            not in {
                                "$eq",
                                "$ne",
                                "$gt",
                                "$gte",
                                "$lt",
                                "$lte",
                                "$in",
                                "$nin",
                                "$exists",
                            }
                            for operator in predicate
                        )
                    )
                ):
                    return None
                dependencies.add(name)
                if len(dependencies) > MAX_PROOF_PATHS:
                    return None
    return tuple(sorted(dependencies))


def capture_read(
    core: LocalCacheCore,
    namespace: NamespaceId,
    policy: SelectiveInvalidation,
    metadata: CollectionMetadata | None,
    filter_document: object,
    *,
    collation: object,
    count: bool = False,
    hinted: bool = False,
) -> NamespaceCaptureView:
    assert metadata is not None
    partition = None
    dependencies = None
    if collation is None or isinstance(collation, (Collation, Mapping)):
        effective_collation = (
            metadata.default_collation
            if collation is None
            else normalize_collation(collation_document(collation))
        )
        if policy.insert_partition_field is not None and effective_collation is None:
            partition = partition_proof(filter_document, policy.insert_partition_field)
    if count and policy.update_dependencies_for_counts and not hinted:
        dependencies = count_dependencies(filter_document)
    return core.capture_namespace_generation(
        namespace,
        partition=partition,
        dependencies=dependencies,
        expected_epoch=metadata.checked_epoch,
    )
