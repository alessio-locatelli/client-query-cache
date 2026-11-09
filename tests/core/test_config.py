from __future__ import annotations

from operator import attrgetter
from typing import TYPE_CHECKING, Literal, get_type_hints

import pytest
from hypothesis import given
from hypothesis import strategies as st

from client_query_cache import CacheConfigurationError, CacheCoreConfig
from client_query_cache._types import NonEmptyStr, NonNegativeInt, PositiveInt

if TYPE_CHECKING:
    from client_query_cache import CacheCore

pytestmark = pytest.mark.unit

_CONFIG_HINTS = get_type_hints(CacheCoreConfig, include_extras=True)


def test_default_budget_and_max_entry_size() -> None:
    config = CacheCoreConfig()
    assert config.budget_bytes == 64 * 1024 * 1024
    assert config.max_entry_bytes == 1024 * 1024
    assert config.max_namespaces == 1024
    assert config.max_entries is None
    assert config.max_key_bytes is None


@pytest.mark.parametrize("field", ["max_entries", "max_key_bytes"])
@pytest.mark.parametrize(
    "limit", [None, 1, 2**100], ids=["disabled", "minimum", "large"]
)
def test_optional_retention_limits(field: str, limit: PositiveInt | None) -> None:
    config = CacheCoreConfig(**{field: limit})  # type: ignore[arg-type]
    assert getattr(config, field) == limit


@pytest.mark.parametrize("field", ["max_entries", "max_key_bytes"])
@pytest.mark.parametrize("limit", [0, -1], ids=["zero", "negative"])
def test_retention_limits_reject_invalid_ranges(field: str, limit: int) -> None:
    with pytest.raises(CacheConfigurationError, match=field):
        CacheCoreConfig(**{field: limit})  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["max_entries", "max_key_bytes"])
def test_retention_limits_reject_invalid_types(
    field: str, invalid_config_integer: object
) -> None:
    if invalid_config_integer is None:
        assert getattr(CacheCoreConfig(**{field: None}), field) is None  # type: ignore[arg-type]
    else:
        with pytest.raises(CacheConfigurationError, match=field):
            CacheCoreConfig(**{field: invalid_config_integer})  # type: ignore[arg-type]


@pytest.mark.parametrize("core", [True], indirect=True, ids=["telemetry"])
def test_removed_budget_interfaces_are_not_aliased(core: CacheCore) -> None:
    with pytest.raises(TypeError, match="shared_budget_bytes"):
        CacheCoreConfig(shared_budget_bytes=1024, enable_telemetry=True)  # type: ignore[call-arg]
    with pytest.raises(AttributeError, match="shared_budget_bytes"):
        attrgetter("shared_budget_bytes")(core.snapshot())


@pytest.mark.parametrize(
    ("budget_bytes", "max_entry_bytes", "message"),
    [
        pytest.param(0, 1, "budget_bytes must be positive", id="zero_budget"),
        pytest.param(-1, 1, "budget_bytes must be positive", id="negative_budget"),
        pytest.param(1, 0, "max_entry_bytes must be positive", id="zero_entry"),
        pytest.param(1, -1, "max_entry_bytes must be positive", id="negative_entry"),
        pytest.param(
            1,
            2,
            "max_entry_bytes must not exceed budget_bytes",
            id="entry_exceeds_budget",
        ),
    ],
)
def test_config_rejects_invalid_budgets(
    budget_bytes: int, max_entry_bytes: int, message: NonEmptyStr
) -> None:
    with pytest.raises(CacheConfigurationError, match=message):
        CacheCoreConfig(budget_bytes=budget_bytes, max_entry_bytes=max_entry_bytes)


@pytest.mark.parametrize("field", ["budget_bytes", "max_entry_bytes", "max_namespaces"])
@pytest.mark.parametrize("peer_value", [1, 0], ids=("valid_peer", "invalid_peer_range"))
def test_config_rejects_non_builtin_integers_before_ranges(
    field: Literal["budget_bytes", "max_entry_bytes", "max_namespaces"],
    peer_value: NonNegativeInt,
    invalid_config_integer: object,
) -> None:
    budgets: dict[
        Literal["budget_bytes", "max_entry_bytes", "max_namespaces"], object
    ] = {
        "budget_bytes": peer_value,
        "max_entry_bytes": peer_value,
        "max_namespaces": peer_value,
    }
    budgets[field] = invalid_config_integer

    with pytest.raises(CacheConfigurationError, match=field):
        CacheCoreConfig(**budgets)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "budget", [1, 64 * 1024 * 1024], ids=("minimum", "default_budget")
)
def test_config_accepts_equal_budgets(budget: PositiveInt) -> None:
    config = CacheCoreConfig(budget_bytes=budget, max_entry_bytes=budget)

    assert config.budget_bytes == budget
    assert config.max_entry_bytes == budget


@given(
    budget_bytes=st.from_type(_CONFIG_HINTS["budget_bytes"]),
    max_entry_bytes=st.from_type(_CONFIG_HINTS["max_entry_bytes"]),
    max_namespaces=st.from_type(_CONFIG_HINTS["max_namespaces"]),
)
def test_config_accepts_every_annotated_budget(
    budget_bytes: PositiveInt,
    max_entry_bytes: PositiveInt,
    max_namespaces: PositiveInt,
) -> None:
    max_entry_bytes = min(max_entry_bytes, budget_bytes)
    config = CacheCoreConfig(
        budget_bytes=budget_bytes,
        max_entry_bytes=max_entry_bytes,
        max_namespaces=max_namespaces,
    )
    assert config.budget_bytes == budget_bytes
    assert config.max_entry_bytes == max_entry_bytes
    assert config.max_namespaces == max_namespaces
