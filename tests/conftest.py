import decimal
import logging
import os
import uuid
from collections.abc import Callable
from copy import copy
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from bson import Decimal128
from faker import Faker

from mongo_client_cache.logger import _logger_debug  # noqa: PLC2701

logger = logging.getLogger(__name__)

logging.basicConfig(level=logging.DEBUG)
_logger_debug.setLevel(logging.DEBUG)
logging.getLogger("faker.factory").setLevel("INFO")
logging.getLogger("pymongo").setLevel("INFO")


@pytest.fixture(autouse=True)
def log_when_test_starts(request: pytest.FixtureRequest) -> None:
    cls_ = f"{request.cls}." if request.cls else ""
    logger.debug(f"Starting '{cls_}{request.node.name}'...")


@pytest.fixture(autouse=True)
def faker_seed() -> str | int:
    ci_pipeline_id = os.getenv("CI_PIPELINE_ID") or os.getenv("GITHUB_JOB")
    default_seed = datetime.now(UTC).day  # Any random value.
    seed = ci_pipeline_id or default_seed
    logger.info(f"Starting pytest session with `Faker.seed` value: {seed}")
    return seed


@pytest.fixture
def cached_database_name() -> str:
    return "db_one"


@pytest.fixture
def persistent_collection_name() -> str:
    return "persistent_collection"


@pytest.fixture
def nonpersistent_collection_name() -> str:
    return "nonpersistent_collection"


@pytest.fixture
def random_document_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def make_fake_document(faker: Faker) -> Callable[..., dict[str, Any]]:
    def _make_fake_document() -> dict[str, Any]:
        document = faker.pydict()
        document["_id"] = str(uuid.uuid4())

        mongo_compatible_document: dict[str, Any] = {}
        for k, v in document.items():
            if isinstance(v, datetime):
                # MongoDB rounds microseconds to the nearest millisecond.
                # If we want to get back the same object, we must round
                # all `datetime` instances before storing them in MongoDB.
                mongo_compatible_document[k] = copy(v).replace(microsecond=0)
            elif isinstance(v, Decimal):
                # `Decimal` must be converted before storing as BSON.
                # Otherwise you will get:
                # ```
                # bson.errors.InvalidDocument: cannot encode object [...]
                # [...] of type: <class 'decimal.Decimal'>
                # ````
                try:
                    mongo_compatible_document[k] = Decimal128(v)
                except decimal.Inexact:
                    continue
            else:
                mongo_compatible_document[k] = v

        return mongo_compatible_document

    return _make_fake_document
