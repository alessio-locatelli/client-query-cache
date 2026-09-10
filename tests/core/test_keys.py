from __future__ import annotations

import pytest

from mongo_client_cache._core.keys import NamespaceId

pytestmark = pytest.mark.unit


def test_namespace_id_exposes_database_and_collection() -> None:
    namespace = NamespaceId("db", "coll")
    assert namespace.database == "db"
    assert namespace.collection == "coll"


def test_namespace_id_equality_is_by_value() -> None:
    assert NamespaceId("db", "coll") == NamespaceId("db", "coll")
    assert NamespaceId("db", "coll") != NamespaceId("db", "other")
