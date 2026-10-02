from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from client_query_cache import BypassReason
from client_query_cache._core.collection_metadata import (
    interpret_list_collections_entry,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Literal

pytestmark = pytest.mark.unit

_UNRECOGNIZED_COLLECTION_TYPE = "future_collection_type"


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
    assert (
        metadata.bypass_reason
        is {
            "collection": None,
            "view": BypassReason.VIEW_COLLECTION,
            "timeseries": BypassReason.TIME_SERIES_COLLECTION,
        }[collection_type]
    )
    assert metadata.default_collation == collation


def test_absent_metadata_requires_another_probe() -> None:
    assert (
        interpret_list_collections_entry(None).bypass_reason
        is BypassReason.MISSING_COLLECTION
    )


def test_collection_without_options_has_no_default_collation() -> None:
    metadata = interpret_list_collections_entry({"type": "collection"})

    assert metadata is not None
    assert metadata.is_cacheable
    assert metadata.default_collation is None


def test_unrecognized_collection_type_remains_ineligible() -> None:
    metadata = interpret_list_collections_entry({"type": _UNRECOGNIZED_COLLECTION_TYPE})
    assert not metadata.is_cacheable
    assert metadata.bypass_reason is BypassReason.METADATA_UNAVAILABLE
