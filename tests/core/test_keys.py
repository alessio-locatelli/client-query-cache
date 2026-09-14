from __future__ import annotations

import pytest

from mongo_client_cache._core.keys import NamespaceId, canonical_alias_key

pytestmark = pytest.mark.unit


def test_namespace_id_exposes_database_and_collection() -> None:
    namespace = NamespaceId("db", "coll")
    assert namespace.database == "db"
    assert namespace.collection == "coll"


def test_namespace_id_equality_is_by_value() -> None:
    assert NamespaceId("db", "coll") == NamespaceId("db", "coll")
    assert NamespaceId("db", "coll") != NamespaceId("db", "other")


def test_alias_key_is_order_sensitive_for_an_embedded_document_value() -> None:
    first = canonical_alias_key("profile", {"a": 1, "b": 2}, None)
    second = canonical_alias_key("profile", {"b": 2, "a": 1}, None)

    assert first != second


def test_alias_key_is_stable_for_a_compound_value_tuple() -> None:
    first = canonical_alias_key(("tenant", "email"), ("t1", "a@example.com"), None)
    second = canonical_alias_key(("tenant", "email"), ("t1", "a@example.com"), None)

    assert first == second
