from __future__ import annotations

from typing import Any

import pytest

from mongo_client_cache._core.unique_keys import (
    UniqueKeyDefinition,
    discover_unique_keys,
    match_unique_key,
)

pytestmark = pytest.mark.unit


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
