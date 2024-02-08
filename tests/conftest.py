import logging
import os
from copy import copy
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from bson import Decimal128
from faker import Faker

logger = logging.getLogger(__name__)

logging.getLogger("faker.factory").setLevel("INFO")
logging.getLogger("pymongo.ocsp_support").setLevel("INFO")
logging.getLogger("pymongo.connectionpool").setLevel("INFO")


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


@pytest.fixture(scope="session")
def collection_name() -> str:
    return "example"


@pytest.fixture
def document_id(faker: Faker) -> int:
    return faker.pyint()


@pytest.fixture
def example_document(faker: Faker, document_id: int) -> dict[str, Any]:
    document = faker.pydict()
    document["_id"] = document_id

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
            mongo_compatible_document[k] = Decimal128(v)
        else:
            mongo_compatible_document[k] = v

    return mongo_compatible_document
