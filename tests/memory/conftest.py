from typing import TYPE_CHECKING, NewType

import pytest
from faker import Faker

from client_query_cache._core.manager import CacheCore, CacheCoreConfig

if TYPE_CHECKING:
    from collections.abc import Iterator

SyntheticPayload = NewType("SyntheticPayload", str)
SHARED_BUDGET_BYTES = 4 * 1024 * 1024


@pytest.fixture
def require_memory_profiling(request: pytest.FixtureRequest) -> None:
    if not request.config.getoption("memray", default=False):
        pytest.fail(
            "Memory tests require active profiling; run just test-memory. "
            "The locked memory tier requires Linux: https://bloomberg.github.io/memray/",
            pytrace=False,
        )
    if not request.config.getoption("trace_python_allocators", default=False):
        pytest.fail("Memory tests require --trace-python-allocators.", pytrace=False)


@pytest.fixture
def synthetic_payload() -> SyntheticPayload:
    generator = Faker()
    generator.seed_instance(0)
    return SyntheticPayload(generator.pystr(min_chars=64 * 1024, max_chars=64 * 1024))


@pytest.fixture
def memory_core() -> Iterator[CacheCore]:
    core = CacheCore(
        CacheCoreConfig(
            shared_budget_bytes=SHARED_BUDGET_BYTES, max_entry_bytes=128 * 1024
        )
    )
    yield core
    core.close()
