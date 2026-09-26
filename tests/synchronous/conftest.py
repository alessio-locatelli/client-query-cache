import logging
from typing import TYPE_CHECKING, Any

import pytest
from pymongo import MongoClient

from client_query_cache.synchronous.manager import CacheManager

if TYPE_CHECKING:
    from collections.abc import Iterator

    from tests.conftest import MongoDbUri

logger = logging.getLogger(__name__)


@pytest.fixture
def raw_mongo_client(
    mongodb_uri: MongoDbUri,
) -> Iterator[MongoClient[dict[str, Any]]]:
    with MongoClient[dict[str, Any]](mongodb_uri) as client:
        yield client


@pytest.fixture
def cache_manager(
    raw_mongo_client: MongoClient[dict[str, Any]],
) -> Iterator[CacheManager[dict[str, Any]]]:
    logger.debug("[SETUP] %s wrapping %s.", CacheManager.__name__, raw_mongo_client)
    manager = CacheManager(raw_mongo_client)
    yield manager
    manager.close()
