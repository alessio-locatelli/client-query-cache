import logging
from typing import TYPE_CHECKING, Any

import pytest
from pymongo import AsyncMongoClient

from mongo_client_cache.asynchronous.manager import CacheManager

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from tests.conftest import MongoDbUri

logger = logging.getLogger(__name__)


@pytest.fixture
async def raw_mongo_client(
    mongodb_uri: MongoDbUri,
) -> AsyncIterator[AsyncMongoClient[dict[str, Any]]]:
    async with AsyncMongoClient[dict[str, Any]](mongodb_uri) as client:
        yield client


@pytest.fixture
def cache_manager(
    raw_mongo_client: AsyncMongoClient[dict[str, Any]],
) -> CacheManager[dict[str, Any]]:
    logger.debug("[SETUP] %s wrapping %s.", CacheManager.__name__, raw_mongo_client)
    return CacheManager(raw_mongo_client)
