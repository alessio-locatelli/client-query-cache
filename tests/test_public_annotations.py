import dataclasses
from typing import get_args, get_type_hints

import pytest
from annotated_types import Ge, Gt

import client_query_cache
import client_query_cache.asynchronous
from client_query_cache import (
    BypassReasonCount,
    CacheCoreConfig,
    CacheSnapshot,
    StreamCostSnapshot,
)

pytestmark = pytest.mark.unit

PUBLIC_DATACLASSES = sorted(
    {
        exported
        for module in (client_query_cache, client_query_cache.asynchronous)
        for exported in (getattr(module, name) for name in module.__all__)
        if isinstance(exported, type) and dataclasses.is_dataclass(exported)
    },
    key=lambda cls: cls.__name__,
)


@pytest.mark.parametrize(
    "cls", PUBLIC_DATACLASSES, ids=[cls.__name__ for cls in PUBLIC_DATACLASSES]
)
def test_public_dataclass_annotations_resolve_at_runtime(cls: type) -> None:
    assert get_type_hints(cls, include_extras=True).keys() == {
        field.name for field in dataclasses.fields(cls)
    }


@pytest.mark.parametrize(
    ("cls", "field", "expected"),
    [
        pytest.param(
            CacheCoreConfig, "shared_budget_bytes", (int, Gt(0)), id="shared-budget"
        ),
        pytest.param(CacheCoreConfig, "max_entry_bytes", (int, Gt(0)), id="entry-size"),
        pytest.param(CacheSnapshot, "hits", (int, Ge(0)), id="snapshot-counter"),
        pytest.param(BypassReasonCount, "count", (int, Ge(0)), id="bypass-count"),
        pytest.param(
            StreamCostSnapshot, "logical_event_bytes", (int, Ge(0)), id="stream-bytes"
        ),
    ],
)
def test_public_fields_carry_their_range_metadata(
    cls: type, field: str, expected: tuple[object, ...]
) -> None:
    alias = get_type_hints(cls, include_extras=True)[field]
    assert get_args(alias.__value__) == expected
