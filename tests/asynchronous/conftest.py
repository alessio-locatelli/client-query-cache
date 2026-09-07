import logging
from collections.abc import AsyncIterator
from typing import Any

import pytest
from pymongo import AsyncMongoClient
from pymongo.asynchronous.collection import AsyncCollection

from mongo_client_cache.asynchronous.manager import CacheManager
from tests.conftest import CollectionName, DatabaseName, MongoDbUri

logger = logging.getLogger(__name__)


@pytest.fixture
async def raw_mongo_client(
    mongodb_uri: MongoDbUri,
) -> AsyncIterator[AsyncMongoClient[dict[str, Any]]]:
    async with AsyncMongoClient[dict[str, Any]](mongodb_uri) as client:
        yield client


@pytest.fixture
def raw_collection(
    raw_mongo_client: AsyncMongoClient[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> AsyncCollection:
    return raw_mongo_client[cached_database_name][nonpersistent_collection_name]


@pytest.fixture
def cache_manager(raw_mongo_client: AsyncMongoClient[dict[str, Any]]) -> CacheManager:
    logger.debug("[SETUP] %s wrapping %s.", CacheManager.__name__, raw_mongo_client)
    return CacheManager(raw_mongo_client)
