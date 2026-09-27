from __future__ import annotations

import os

import pytest

_REDACTED = "<redacted>"


class RealMongoDbUri:
    __slots__ = ("_raw",)

    def __init__(self, raw: str) -> None:
        self._raw = raw

    def get_secret_value(self) -> str:
        return self._raw

    def __repr__(self) -> str:
        return f"RealMongoDbUri({_REDACTED})"

    def __str__(self) -> str:
        return _REDACTED


_CI_ENV_VARS = ("GITHUB_ACTIONS", "CI")
_TRUTHY_VALUES = frozenset({"true", "1", "yes"})
_URI_ENV_VAR = "REAL_MONGODB_URI"


def resolve_real_mongodb_uri() -> RealMongoDbUri:
    if any(os.environ.get(name, "").lower() in _TRUTHY_VALUES for name in _CI_ENV_VARS):
        pytest.skip("Real-server benchmark does not run in CI.")
    uri = os.environ.get(_URI_ENV_VAR)
    if not uri:
        pytest.skip(
            f"Real-server benchmark requires {_URI_ENV_VAR} in a local .env file."
        )
    return RealMongoDbUri(uri)
