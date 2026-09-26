from __future__ import annotations

import os
from typing import NewType

import pytest

RealMongoDbUri = NewType("RealMongoDbUri", str)

_CI_ENV_VARS = ("GITHUB_ACTIONS", "CI")
_URI_ENV_VAR = "REAL_MONGODB_URI"


def resolve_real_mongodb_uri() -> RealMongoDbUri:
    if any(os.environ.get(name) == "true" for name in _CI_ENV_VARS):
        pytest.skip("Real-server benchmark does not run in CI.")
    uri = os.environ.get(_URI_ENV_VAR)
    if not uri:
        pytest.skip(
            f"Real-server benchmark requires {_URI_ENV_VAR} in a local .env file."
        )
    return RealMongoDbUri(uri)
