from dataclasses import FrozenInstanceError

import pytest
from bson import ObjectId
from bson.decimal128 import Decimal128
from bson.int64 import Int64
from hypothesis import given
from hypothesis import strategies as st

from client_query_cache import SelectiveInvalidation
from client_query_cache._core.errors import CacheConfigurationError
from client_query_cache._core.selective_invalidation import (
    count_dependencies,
    normalize_invalidation,
    partition_proof,
    partition_scalar,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("field", ["", "a.b", "$author", "author\0id", 1])
def test_partition_field_validation(field: object) -> None:
    with pytest.raises(CacheConfigurationError):
        SelectiveInvalidation(insert_partition_field=field)  # type: ignore[arg-type]


@pytest.mark.parametrize("flag", [0, 1, None, "true"])
def test_update_flag_requires_boolean(flag: object) -> None:
    with pytest.raises(CacheConfigurationError):
        SelectiveInvalidation(update_dependencies_for_counts=flag)  # type: ignore[arg-type]


def test_policy_and_normalized_maps_are_immutable() -> None:
    policy = SelectiveInvalidation(insert_partition_field="author_id")
    with pytest.raises(FrozenInstanceError):
        policy.insert_partition_field = "other"  # type: ignore[misc]
    normalized = normalize_invalidation({("example", "posts"): policy})
    with pytest.raises(TypeError):
        normalized["example"]["posts"] = SelectiveInvalidation()  # type: ignore[index]
    with pytest.raises(TypeError):
        normalized["other"] = {}  # type: ignore[index]


@pytest.mark.parametrize(
    "configuration", [None, {}, {("example", "posts"): SelectiveInvalidation()}]
)
def test_disabled_configuration_has_no_runtime_policies(configuration: object) -> None:
    assert not normalize_invalidation(configuration)  # type: ignore[arg-type]


def test_nonmapping_policy_configuration_is_rejected() -> None:
    with pytest.raises(CacheConfigurationError, match="mapping"):
        normalize_invalidation([])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "value", [None, [], {}, 42.0, Decimal128("42"), "é" * 33, "a" * 65, 2**63]
)
def test_unsupported_partition_scalars_fall_back(value: object) -> None:
    assert partition_scalar(value) is None


@pytest.mark.parametrize(
    "value",
    [42, Int64(42), True, False, "é" * 32, ObjectId()],
    ids=["int", "long", "true", "false", "string-boundary", "object-id"],
)
def test_supported_partition_equalities(value: object) -> None:
    expected = partition_scalar(value)
    assert expected is not None
    assert (
        partition_proof({"author_id": value, "published": True}, "author_id")
        == expected
    )
    assert (
        partition_proof(
            {"$and": [{"author_id": {"$eq": value}}, {"views": {"$gt": 0}}]},
            "author_id",
        )
        == expected
    )


def test_integer_subtypes_match_but_booleans_remain_distinct() -> None:
    assert partition_scalar(42) == partition_scalar(Int64(42))
    assert partition_scalar(1) != partition_scalar(value=True)
    assert partition_scalar(0) != partition_scalar(value=False)


@given(st.integers(min_value=-(2**63), max_value=2**63 - 1))
def test_bson_integer_partition_identity_preserves_type_boundaries(value: int) -> None:
    assert partition_scalar(value) == partition_scalar(Int64(value))
    assert partition_scalar(value) != partition_scalar(bool(value))
    assert partition_scalar(float(value)) is None
    assert partition_scalar(Decimal128(str(value))) is None


@given(st.text(alphabet=st.characters(codec="utf-8"), max_size=80))
def test_partition_string_bound_uses_utf8_bytes(value: str) -> None:
    assert (partition_scalar(value) is not None) is (len(value.encode("utf-8")) <= 64)


@pytest.mark.parametrize("logical", ["$and", "$or", "$nor"])
def test_unrelated_logical_conjunct_preserves_independent_partition(
    logical: str,
) -> None:
    predicate = {
        "$and": [{"author_id": 42}, {logical: [{"published": True}, {"draft": True}]}]
    }
    assert partition_proof(predicate, "author_id") == partition_scalar(42)


@pytest.mark.parametrize(
    "predicate",
    [
        None,
        {},
        {"$and": []},
        {"author_id": 42, "$or": [1]},
        {"author_id": 42, "$or": []},
        {"author_id": 42, "$expr": {"$eq": ["$views", 0]}},
        {"$and": [{"author_id": 42}, 1]},
        {"author_id": None},
        {"author_id": {"$in": [42]}},
        {"$or": [{"author_id": 42}, {"author_id": 99}]},
        {"$and": [{"author_id": 42}, {"author_id": 99}]},
        {"$and": [{"author_id": 42}, {"author_id": {"$gt": 0}}]},
        {"author_id": 42, "author_id.child": 1},
    ],
)
def test_unproved_partition_filters_fall_back(predicate: object) -> None:
    assert partition_proof(predicate, "author_id") is None


@given(st.permutations(({"author_id": 42}, {"views": {"$gt": 0}}, {"published": True})))
def test_partition_proof_is_independent_of_conjunction_order(
    conjuncts: tuple[object, ...],
) -> None:
    assert partition_proof({"$and": conjuncts}, "author_id") == partition_scalar(42)


@pytest.mark.parametrize(
    ("predicate", "expected"),
    [
        (None, None),
        ({}, ()),
        (
            {"profile.country": "UA", "tags": {"$in": ["python"]}},
            ("profile.country", "tags"),
        ),
        ({"$or": [{"a": None}, {"b": {"$exists": False}}]}, ("a", "b")),
        ({"$nor": [{"a": {"$nin": [1]}}, {"b": {"$ne": 2}}]}, ("a", "b")),
        ({"$expr": {"$eq": ["$a", "$b"]}}, None),
        ({"a": {"$regex": "x"}}, None),
        ({"a.0": 1}, None),
        ({"a..b": 1}, None),
        ({"$and": []}, None),
        ({"$and": [1]}, None),
        ({"é" * 33: 1}, None),
        ({str(index) + "x": 1 for index in range(33)}, None),
    ],
)
def test_count_dependency_subset(predicate: object, expected: object) -> None:
    assert count_dependencies(predicate) == expected


@given(
    st.lists(st.from_regex(r"[a-z]{1,12}", fullmatch=True), max_size=32, unique=True)
)
def test_dependency_union_is_independent_of_logical_order(fields: list[str]) -> None:
    if fields:
        predicate = {"$and": [{field: {"$exists": True}} for field in fields]}
    else:
        predicate = {}
    assert count_dependencies(predicate) == tuple(sorted(fields))
