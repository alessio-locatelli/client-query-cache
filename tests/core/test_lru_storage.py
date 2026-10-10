from __future__ import annotations

from typing import TYPE_CHECKING, Literal, get_type_hints

import pytest
from hypothesis import given
from hypothesis import strategies as st

from client_query_cache import CacheConfigurationError
from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.manager import CacheCore, CacheCoreConfig
from client_query_cache._types import NonEmptyStr, NonNegativeInt, PositiveInt

if TYPE_CHECKING:
    from collections.abc import Callable

    from client_query_cache._core.keys import NamespaceId

pytestmark = pytest.mark.unit

_CONFIG_HINTS = get_type_hints(CacheCoreConfig, include_extras=True)


def test_default_budget_and_max_entry_size() -> None:
    config = CacheCoreConfig()
    assert config.shared_budget_bytes == 64 * 1024 * 1024
    assert config.max_entry_bytes == 1024 * 1024


@pytest.mark.parametrize(
    ("shared_budget_bytes", "max_entry_bytes", "message"),
    [
        pytest.param(0, 1, "shared_budget_bytes must be positive", id="zero_budget"),
        pytest.param(
            -1, 1, "shared_budget_bytes must be positive", id="negative_budget"
        ),
        pytest.param(1, 0, "max_entry_bytes must be positive", id="zero_entry"),
        pytest.param(1, -1, "max_entry_bytes must be positive", id="negative_entry"),
        pytest.param(
            1,
            2,
            "max_entry_bytes must not exceed shared_budget_bytes",
            id="entry_exceeds_budget",
        ),
    ],
)
def test_config_rejects_invalid_budgets(
    shared_budget_bytes: int, max_entry_bytes: int, message: NonEmptyStr
) -> None:
    with pytest.raises(CacheConfigurationError, match=message):
        CacheCoreConfig(
            shared_budget_bytes=shared_budget_bytes, max_entry_bytes=max_entry_bytes
        )


@pytest.mark.parametrize("field", ["shared_budget_bytes", "max_entry_bytes"])
@pytest.mark.parametrize("peer_value", [1, 0], ids=("valid_peer", "invalid_peer_range"))
def test_config_rejects_non_builtin_integers_before_ranges(
    field: Literal["shared_budget_bytes", "max_entry_bytes"],
    peer_value: NonNegativeInt,
    invalid_config_integer: object,
) -> None:
    budgets: dict[Literal["shared_budget_bytes", "max_entry_bytes"], object] = {
        "shared_budget_bytes": peer_value,
        "max_entry_bytes": peer_value,
    }
    budgets[field] = invalid_config_integer

    with pytest.raises(CacheConfigurationError, match=field):
        CacheCoreConfig(**budgets)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "budget", [1, 64 * 1024 * 1024], ids=("minimum", "default_budget")
)
def test_config_accepts_equal_budgets(budget: PositiveInt) -> None:
    config = CacheCoreConfig(shared_budget_bytes=budget, max_entry_bytes=budget)

    assert config.shared_budget_bytes == budget
    assert config.max_entry_bytes == budget


@given(
    shared_budget_bytes=st.from_type(_CONFIG_HINTS["shared_budget_bytes"]),
    max_entry_bytes=st.from_type(_CONFIG_HINTS["max_entry_bytes"]),
)
def test_config_accepts_every_annotated_budget(
    shared_budget_bytes: PositiveInt, max_entry_bytes: PositiveInt
) -> None:
    max_entry_bytes = min(max_entry_bytes, shared_budget_bytes)
    config = CacheCoreConfig(
        shared_budget_bytes=shared_budget_bytes, max_entry_bytes=max_entry_bytes
    )
    assert config.shared_budget_bytes == shared_budget_bytes
    assert config.max_entry_bytes == max_entry_bytes


def test_eviction_keeps_used_bytes_within_the_shared_budget(
    namespace: NamespaceId,
) -> None:
    shared_budget_bytes = 2_000
    core = CacheCore(
        CacheCoreConfig(shared_budget_bytes=shared_budget_bytes, max_entry_bytes=200)
    )
    for index in range(100):
        capture = core.begin_identity_admission(namespace, f"doc-{index}")
        outcome = core.admit_identity(capture, "full", {"v": "x" * 100})
        assert outcome is AdmissionOutcome.ADMITTED

    used_bytes, _entry_count = core._lru.snapshot_usage()
    assert used_bytes <= shared_budget_bytes


def test_eviction_updates_the_owning_namespaces_index_after_the_lru_lock_releases(
    namespace: NamespaceId,
) -> None:
    core = CacheCore(CacheCoreConfig(shared_budget_bytes=300, max_entry_bytes=200))
    evicted_identity = "doc-0"
    capture = core.begin_identity_admission(namespace, evicted_identity)
    core.admit_identity(capture, "full", {"v": "x" * 100})

    for index in range(1, 20):
        capture = core.begin_identity_admission(namespace, f"doc-{index}")
        core.admit_identity(capture, "full", {"v": "x" * 100})

    state = core._namespace(namespace)
    live_identities = {
        entry.identity for entry in state.entry_index if entry.identity is not None
    }
    assert evicted_identity not in live_identities
    assert evicted_identity not in state.identities


def test_the_shared_budget_is_shared_across_namespaces(
    namespace: NamespaceId, other_namespace: NamespaceId
) -> None:
    core = CacheCore(CacheCoreConfig(shared_budget_bytes=300, max_entry_bytes=200))
    capture_a = core.begin_identity_admission(namespace, "doc-a")
    core.admit_identity(capture_a, "full", {"v": "x" * 100})

    capture_b = core.begin_identity_admission(other_namespace, "doc-b")
    core.admit_identity(capture_b, "full", {"v": "x" * 100})

    for index in range(20):
        capture = core.begin_identity_admission(other_namespace, f"doc-flood-{index}")
        core.admit_identity(capture, "full", {"v": "x" * 100})

    lookup_result = core.lookup_identity(namespace, "doc-a", "full")
    assert lookup_result.hit is False


@pytest.mark.parametrize(
    "admit_oversize",
    [
        pytest.param(
            lambda core, namespace: core.admit_identity(
                core.begin_identity_admission(namespace, "doc-1"),
                "full",
                {"payload": "x" * 200},
            ),
            id="identity_guarded",
        ),
        pytest.param(
            lambda core, namespace: core.admit_namespace(
                core.capture_namespace_generation(namespace),
                ("find", {}),
                ["x" * 200],
            ),
            id="namespace_guarded",
        ),
    ],
)
def test_oversize_value_is_declined_without_touching_the_budget(
    namespace: NamespaceId,
    admit_oversize: Callable[[CacheCore, NamespaceId], AdmissionOutcome],
) -> None:
    core = CacheCore(CacheCoreConfig(shared_budget_bytes=1_000, max_entry_bytes=32))

    outcome = admit_oversize(core, namespace)

    assert outcome is AdmissionOutcome.DECLINED_OVERSIZE
    used_bytes, entry_count = core._lru.snapshot_usage()
    assert used_bytes == 0
    assert entry_count == 0
