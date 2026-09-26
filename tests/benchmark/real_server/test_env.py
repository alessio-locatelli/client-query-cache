from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.benchmark.real_server.env import resolve_real_mongodb_uri

if TYPE_CHECKING:
    from faker import Faker

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clear_real_server_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("REAL_MONGODB_URI", raising=False)


@pytest.mark.parametrize(
    ("env", "match"),
    [
        pytest.param({"GITHUB_ACTIONS": "true"}, "CI", id="github_actions"),
        pytest.param({"GITHUB_ACTIONS": "True"}, "CI", id="github_actions_capitalized"),
        pytest.param({"CI": "true"}, "CI", id="ci"),
        pytest.param({"CI": "1"}, "CI", id="ci_numeric"),
        pytest.param({}, "REAL_MONGODB_URI", id="missing_uri"),
    ],
)
def test_resolve_real_mongodb_uri_skips(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], match: str
) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(pytest.skip.Exception, match=match):
        resolve_real_mongodb_uri()


def test_resolve_real_mongodb_uri_returns_the_configured_uri(
    monkeypatch: pytest.MonkeyPatch, faker: Faker
) -> None:
    uri = faker.uri()
    monkeypatch.setenv("REAL_MONGODB_URI", uri)

    assert resolve_real_mongodb_uri() == uri
