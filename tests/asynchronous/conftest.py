import logging
from typing import TYPE_CHECKING

import pytest
from pymongo import AsyncMongoClient

from client_query_cache._types import BsonDict
from client_query_cache.asynchronous.manager import CacheManager

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from tests.conftest import MongoDbUri

logger = logging.getLogger(__name__)


@pytest.fixture
async def raw_mongo_client(
    mongodb_uri: MongoDbUri,
) -> AsyncIterator[AsyncMongoClient[BsonDict]]:
    async with AsyncMongoClient[BsonDict](mongodb_uri) as client:
        yield client


@pytest.fixture
async def cache_manager(
    raw_mongo_client: AsyncMongoClient[BsonDict],
) -> AsyncIterator[CacheManager[BsonDict]]:
    logger.debug("[SETUP] %s wrapping %s.", CacheManager.__name__, raw_mongo_client)
    manager = CacheManager(raw_mongo_client)
    yield manager
    await manager.close()
