"""Run explicitly selected behavioral tests against the installed native owner.

Load with ``-p research.native_process_local_cache.pytest_plugin``. Tests that
exercise Python reference storage internals are separate from this selection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from client_query_cache._core.manager import CacheCore as ReferenceCore  # noqa: PLC2701 - Select the experimental core for existing behavioral cases.
from client_query_cache.asynchronous import CacheManager as AsyncManager
from client_query_cache.asynchronous import manager as async_module
from client_query_cache.synchronous import CacheManager as SyncManager
from client_query_cache.synchronous import manager as sync_module
from research.native_process_local_cache.selection import (
    native_core_type,
    select_native,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from _pytest.fixtures import FixtureDef


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--native-managers-only", action="store_true")


def pytest_configure() -> None:
    select_native()


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("--native-managers-only"):
        return
    native = native_core_type()
    for item in items:
        module = item.getparent(pytest.Module)
        if (
            module is not None
            and module.obj.__name__.startswith("tests.")
            and "CacheCore" in vars(module.obj)
            and vars(module.obj)["CacheCore"] is ReferenceCore
        ):
            vars(module.obj)["CacheCore"] = native


@pytest.hookimpl(wrapper=True)
def pytest_fixture_setup(
    fixturedef: FixtureDef[object],
    request: pytest.FixtureRequest,
) -> Generator[None, object, object]:
    select_core = not request.config.getoption("--native-managers-only")
    if fixturedef.argname == "core" and select_core:
        # Directory conftest fixtures have precedence over plugin fixtures.
        # Replace that fixture's constructor, not the shared owner's constructor.
        namespace = fixturedef.func.__globals__
        if namespace["CacheCore"] is ReferenceCore:
            namespace["CacheCore"] = native_core_type()
    fixture_value = yield
    if fixturedef.argname == "core" and select_core:
        assert isinstance(fixture_value, native_core_type())
    if isinstance(fixture_value, (SyncManager, AsyncManager)):
        expected = (
            ReferenceCore if _reference_case(request.node) else native_core_type()
        )
        assert isinstance(fixture_value.cache_core, expected)
        assert fixture_value._coordinator._cache is fixture_value.cache_core  # noqa: SLF001 - Native attribution requires the coordinator to own the same core.
    return fixture_value


def _reference_case(item: pytest.Item) -> bool:
    # These cases mutate Python storage or patch reference class methods. They
    # continue to exercise the retained reference/shared-owner implementation.
    name = item.name.split("[", 1)[0]
    return (
        "evicted_alias" in getattr(item, "fixturenames", ())
        or str(item.path).endswith("tests/benchmark/test_cached_read_cursors.py")
        or name
        in {
            "test_a_revalidated_positive_match_overwrites_a_stale_namespace_entry",
            "test_an_uncanonicalizable_revalidated_identity_discards_the_stale_alias",
            "test_reads_spanning_invalidation_or_recovery_are_not_admitted",
            "test_reads_recheck_availability_before_forcing_read_options",
            "test_a_resolved_unique_key_read_rechecks_availability_before_forcing_read_options",
            "test_a_resolved_unique_key_read_rechecks_availability_before_forcing_options",
            "test_stop_racing_a_successful_reopen_leaves_cache_unavailable",
            "test_unhealthy_transition_disables_cache_before_publishing_health",
            "test_rejects_invalid_workload_measurements",
        }
    )


@pytest.fixture(autouse=True)
def _manager_selection(
    request: pytest.FixtureRequest,
) -> Generator[None]:
    reference = _reference_case(request.node)
    core = ReferenceCore if reference else native_core_type()
    request.node.user_properties.append(("manager_constructor", core.__module__))
    # A separate patch context preserves the ordering of tests' own monkeypatch
    # fixture relative to their manager cleanup.
    with pytest.MonkeyPatch.context() as selection:
        selection.setattr(sync_module, "CacheCore", core)
        selection.setattr(async_module, "CacheCore", core)
        yield
