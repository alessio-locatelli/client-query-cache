import logging
from typing import TYPE_CHECKING, Any

import pytest
from pymongo import MongoClient

from mongo_client_cache.synchronous.manager import CacheManager

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pymongo.synchronous.collection import Collection

    from tests.conftest import CollectionName, DatabaseName, MongoDbUri

logger = logging.getLogger(__name__)


@pytest.fixture
def raw_mongo_client(
    mongodb_uri: MongoDbUri,
) -> Iterator[MongoClient[dict[str, Any]]]:
    with MongoClient[dict[str, Any]](mongodb_uri) as client:
        yield client


@pytest.fixture
def raw_collection(
    raw_mongo_client: MongoClient[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> Collection[dict[str, Any]]:
    return raw_mongo_client[cached_database_name][nonpersistent_collection_name]


@pytest.fixture
def cache_manager(
    raw_mongo_client: MongoClient[dict[str, Any]],
) -> CacheManager[dict[str, Any]]:
    logger.debug("[SETUP] %s wrapping %s.", CacheManager.__name__, raw_mongo_client)
    return CacheManager(raw_mongo_client)
