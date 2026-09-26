from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from client_query_cache._core.unique_keys import (
    UniqueKeyDefinition,
    discover_unique_keys,
    match_unique_key,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

pytestmark = pytest.mark.unit

_FIELD_NAME_POOL = ("a", "b", "c", "d")
_COLLATIONS = (None, {"locale": "en", "strength": 2})
_EQUALITY_VALUES = st.integers(min_value=-100, max_value=100) | st.text(max_size=5)
_OPERATOR_VALUES = st.sampled_from(({"$in": [1, 2]}, {"$exists": True}, {"$gt": 1}))


@st.composite
def _unique_key_definitions(draw: st.DrawFn) -> UniqueKeyDefinition:
    fields = tuple(
        draw(
            st.lists(
                st.sampled_from(_FIELD_NAME_POOL), min_size=1, max_size=3, unique=True
            )
        )
    )
    collation = draw(st.sampled_from(_COLLATIONS))
    return UniqueKeyDefinition(fields=fields, collation=collation)


@st.composite
def _filters_and_expected_matches(
    draw: st.DrawFn,
) -> tuple[UniqueKeyDefinition, dict[str, object], Mapping[str, Any] | None, bool]:
    definition = draw(_unique_key_definitions())
    shape = draw(st.sampled_from(("exact", "extra", "missing")))
    field_is_equality = {field: draw(st.booleans()) for field in definition.fields}
    if shape == "extra":
        outside_fields = [
            field for field in _FIELD_NAME_POOL if field not in definition.fields
        ]
        field_is_equality[draw(st.sampled_from(outside_fields))] = True
    elif shape == "missing":
        del field_is_equality[draw(st.sampled_from(definition.fields))]
    filter_collation = draw(st.sampled_from((definition.collation, *_COLLATIONS)))
    filter_query = {
        field: draw(_EQUALITY_VALUES) if is_equality else draw(_OPERATOR_VALUES)
        for field, is_equality in field_is_equality.items()
    }
    expected_match = (
        shape == "exact"
        and filter_collation == definition.collation
        and all(field_is_equality.values())
    )
    return definition, filter_query, filter_collation, expected_match


@pytest.mark.parametrize(
    ("index_spec", "expected"),
    [
        pytest.param(
            {"key": {"email": 1}, "name": "email_1", "unique": True},
            (UniqueKeyDefinition(fields=("email",), collation=None),),
            id="single-field-unique",
        ),
        pytest.param(
            {"key": {"tenant": 1, "email": 1}, "name": "compound", "unique": True},
            (UniqueKeyDefinition(fields=("tenant", "email"), collation=None),),
            id="compound-unique-preserves-field-order",
        ),
        pytest.param(
            {
                "key": {"email": 1},
                "name": "email_ci",
                "unique": True,
                "collation": {"locale": "en", "strength": 2},
            },
            (
                UniqueKeyDefinition(
                    fields=("email",), collation={"locale": "en", "strength": 2}
                ),
            ),
            id="unique-index-with-collation",
        ),
        pytest.param(
            {"key": {"email": 1}, "name": "email_1"},
            (),
            id="non-unique-index-excluded",
        ),
        pytest.param(
            {
                "key": {"email": 1},
                "name": "email_partial",
                "unique": True,
                "partialFilterExpression": {"email": {"$exists": True}},
            },
            (),
            id="partial-unique-index-excluded",
        ),
        pytest.param(
            {
                "key": {"email": 1},
                "name": "email_sparse",
                "unique": True,
                "sparse": True,
            },
            (),
            id="sparse-unique-index-excluded",
        ),
        pytest.param(
            {"key": {"email": "hashed"}, "name": "email_hashed", "unique": True},
            (),
            id="hashed-unique-index-excluded",
        ),
        pytest.param(
            {"key": {"_id": 1}, "name": "_id_"},
            (),
            id="default-id-index-excluded",
        ),
        pytest.param(
            {
                "key": {"email": 1},
                "name": "email_simple",
                "unique": True,
                "collation": {"locale": "simple"},
            },
            (UniqueKeyDefinition(fields=("email",), collation=None),),
            id="unique-index-with-simple-collation-normalized-to-none",
        ),
    ],
)
def test_discover_unique_keys_filters_by_index_shape(
    index_spec: dict[str, object], expected: tuple[UniqueKeyDefinition, ...]
) -> None:
    assert discover_unique_keys([index_spec]) == expected


def test_discover_unique_keys_returns_every_eligible_index() -> None:
    index_specs: list[dict[str, Any]] = [
        {"key": {"email": 1}, "name": "email_1", "unique": True},
        {"key": {"username": 1}, "name": "username_1", "unique": True},
        {"key": {"tag": 1}, "name": "tag_1"},
    ]

    keys = discover_unique_keys(index_specs)

    assert keys == (
        UniqueKeyDefinition(fields=("email",), collation=None),
        UniqueKeyDefinition(fields=("username",), collation=None),
    )


_EMAIL_KEY = UniqueKeyDefinition(fields=("email",), collation=None)
_COMPOUND_KEY = UniqueKeyDefinition(fields=("tenant", "email"), collation=None)
_CI_KEY = UniqueKeyDefinition(
    fields=("email",), collation={"locale": "en", "strength": 2}
)


def test_match_unique_key_matches_a_single_field_equality_filter() -> None:
    matched_key = match_unique_key({"email": "a@example.com"}, [_EMAIL_KEY], None)

    assert matched_key == (_EMAIL_KEY, ("a@example.com",))


def test_match_unique_key_matches_a_compound_filter_regardless_of_field_order() -> None:
    matched_key = match_unique_key(
        {"email": "a@example.com", "tenant": "t1"}, [_COMPOUND_KEY], None
    )

    assert matched_key == (_COMPOUND_KEY, ("t1", "a@example.com"))


@pytest.mark.parametrize(
    "filter_query",
    [
        pytest.param({"email": "a@example.com", "extra": "field"}, id="extra-field"),
        pytest.param({"tenant": "t1"}, id="missing-field-of-compound-key"),
        pytest.param({"email": {"$in": ["a@example.com"]}}, id="query-operator-value"),
        pytest.param({"email": None}, id="none-value"),
        pytest.param("not-a-mapping", id="non-mapping-filter"),
        pytest.param({"email": float("nan")}, id="uncanonicalizable-nan-value"),
        pytest.param({"email": {1, 2, 3}}, id="uncanonicalizable-unhashable-value"),
        pytest.param({"email": []}, id="empty-array-value"),
    ],
)
def test_match_unique_key_does_not_match_an_ineligible_filter(
    filter_query: object,
) -> None:
    assert match_unique_key(filter_query, [_EMAIL_KEY, _COMPOUND_KEY], None) is None


def test_match_unique_key_does_not_match_when_collation_differs() -> None:
    assert match_unique_key({"email": "value"}, [_CI_KEY], None) is None


def test_match_unique_key_matches_when_collation_is_identical() -> None:
    collation = {"locale": "en", "strength": 2}
    matched_key = match_unique_key({"email": "value"}, [_CI_KEY], collation)

    assert matched_key == (_CI_KEY, ("value",))


def test_match_unique_key_returns_none_when_no_keys_are_discovered() -> None:
    assert match_unique_key({"email": "value"}, [], None) is None


def test_match_unique_key_matches_simple_collation_index_against_default() -> None:
    keys = discover_unique_keys(
        [
            {
                "key": {"email": 1},
                "name": "email_simple",
                "unique": True,
                "collation": {"locale": "simple"},
            }
        ]
    )

    matched_key = match_unique_key({"email": "value"}, keys, None)

    assert matched_key == (keys[0], ("value",))


@given(_filters_and_expected_matches())
@example((UniqueKeyDefinition(fields=("a",), collation=None), {"a": 1}, None, True))
def test_match_unique_key_matches_iff_field_set_collation_and_equality_align(
    case: tuple[UniqueKeyDefinition, dict[str, object], Mapping[str, Any] | None, bool],
) -> None:
    definition, filter_query, filter_collation, expected_match = case

    matched = match_unique_key(filter_query, [definition], filter_collation)

    assert (matched is not None) == expected_match
    if expected_match:
        assert matched is not None
        assert matched[0] == definition


_INDEX_FIELD_NAMES = ("a", "b", "c")


@st.composite
def _index_specs(draw: st.DrawFn) -> dict[str, Any]:
    fields = draw(
        st.lists(
            st.sampled_from(_INDEX_FIELD_NAMES), min_size=1, max_size=3, unique=True
        )
    )
    key = {field: draw(st.sampled_from((1, -1, "hashed"))) for field in fields}
    spec: dict[str, Any] = {"key": key, "name": "idx"}
    if draw(st.booleans()):
        spec["unique"] = True
    if draw(st.booleans()):
        spec["sparse"] = True
    if draw(st.booleans()):
        spec["partialFilterExpression"] = {fields[0]: {"$exists": True}}
    return spec


@given(_index_specs())
def test_discover_unique_keys_includes_an_index_iff_eligible(
    index_spec: dict[str, Any],
) -> None:
    discovered = discover_unique_keys([index_spec])

    is_hashed = any(value == "hashed" for value in index_spec["key"].values())
    expected_included = (
        index_spec.get("unique", False) is True
        and index_spec.get("sparse", False) is not True
        and "partialFilterExpression" not in index_spec
        and not is_hashed
    )

    assert bool(discovered) is expected_included
    if expected_included:
        assert discovered == (
            UniqueKeyDefinition(fields=tuple(index_spec["key"]), collation=None),
        )
