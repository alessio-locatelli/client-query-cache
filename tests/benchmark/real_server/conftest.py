from __future__ import annotations

import pytest

from tests.benchmark.real_server.env import RealMongoDbUri, resolve_real_mongodb_uri


@pytest.fixture(scope="session")
def real_mongodb_uri() -> RealMongoDbUri:
    return resolve_real_mongodb_uri()
