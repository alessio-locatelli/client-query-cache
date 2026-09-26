from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mongo_client_cache._core.collection_metadata import (
    interpret_list_collections_entry,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Literal

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("collection_type", "cacheable"),
    [("collection", True), ("view", False), ("timeseries", False)],
    ids=["ordinary", "view", "timeseries"],
)
@pytest.mark.parametrize(
    "collation", [None, {"locale": "en", "strength": 2}], ids=["default", "custom"]
)
def test_confirmed_collection_metadata(
    collection_type: Literal["collection", "view", "timeseries"],
    cacheable: bool,
    collation: Mapping[str, object] | None,
) -> None:
    metadata = interpret_list_collections_entry(
        {"type": collection_type, "options": {"collation": collation}}
    )
    assert metadata is not None
    assert metadata.is_cacheable is cacheable
    assert metadata.default_collation == collation


@pytest.mark.parametrize(
    "entry",
    [None, {}, {"type": "unknown"}],
    ids=["absent", "missing-type", "unknown-type"],
)
def test_inconclusive_metadata_requires_another_probe(
    entry: Mapping[str, object] | None,
) -> None:
    assert interpret_list_collections_entry(entry) is None
