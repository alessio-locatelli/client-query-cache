from __future__ import annotations

import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from typing import TYPE_CHECKING, NamedTuple

import pytest

from client_query_cache import CacheCore, CacheCoreConfig
from client_query_cache._core.codec import encode_value
from client_query_cache._core.keys import NamespaceId, canonical_alias_key

if TYPE_CHECKING:
    from collections.abc import Generator

    from faker import Faker

    from client_query_cache._core.contracts import IdentityCaptureView
    from client_query_cache._types import NonEmptyStr


class _IntegerSubclass(int):
    __slots__ = ()


@pytest.fixture
def spawned_worker() -> Generator[ProcessPoolExecutor]:
    with ProcessPoolExecutor(
        max_workers=1, mp_context=multiprocessing.get_context("spawn")
    ) as pool:
        yield pool


@pytest.fixture(
    params=[
        pytest.param(True, id="true"),
        pytest.param(False, id="false"),
        pytest.param(_IntegerSubclass(1), id="integer_subclass"),
        pytest.param(1.0, id="integral_float"),
        pytest.param(1.5, id="fractional_float"),
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="positive_infinity"),
        pytest.param(float("-inf"), id="negative_infinity"),
        pytest.param("1", id="string"),
        pytest.param(None, id="null"),
        pytest.param(object(), id="unrelated_object"),
    ]
)
def invalid_config_integer(request: pytest.FixtureRequest) -> object:
    return request.param


@pytest.fixture
def namespace() -> NamespaceId:
    return NamespaceId("test_db", "test_collection")


@pytest.fixture
def other_namespace() -> NamespaceId:
    return NamespaceId("test_db", "other_collection")


@pytest.fixture(params=[False], ids=["default"])
def core(request: pytest.FixtureRequest) -> CacheCore:
    return CacheCore(CacheCoreConfig(enable_telemetry=request.param))


class PinnedAlias(NamedTuple):
    core: CacheCore
    namespace: NamespaceId
    identity: NonEmptyStr
    value: NonEmptyStr
    capture: IdentityCaptureView


def evict_by_pressure(core: CacheCore, namespace: NamespaceId, value: object) -> None:
    core.admit_namespace(
        core.capture_namespace_generation(namespace), "pressure", value
    )


@pytest.fixture
def pinned_alias(namespace: NamespaceId, faker: Faker) -> Generator[PinnedAlias]:
    identity = faker.uuid4()
    value = faker.pystr(min_chars=30, max_chars=30)
    weight = len(encode_value(value))
    core = CacheCore(CacheCoreConfig(budget_bytes=weight, max_entry_bytes=weight))
    alias = canonical_alias_key("code", identity, None)
    for _ in range(2):
        core.admit_identity(
            core.begin_identity_admission(namespace, identity),
            None,
            value,
            alias=alias,
        )
    capture = core.begin_identity_admission(namespace, identity)
    yield PinnedAlias(core, namespace, identity, value, capture)
    capture.release()
    core.close()
