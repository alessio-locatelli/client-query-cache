from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Self, cast

import pytest
from pymongo.errors import AutoReconnect, OperationFailure

from tests import conftest as project_fixtures

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pymongo import MongoClient

pytestmark = pytest.mark.unit


class _DelayedMongoClient:
    __slots__ = ()
    ping_attempts: ClassVar[int] = 0
    hello_attempts: ClassVar[int] = 0
    always_fail_ping: ClassVar[bool] = False
    permanent_error_on: ClassVar[str | None] = None

    def __class_getitem__(cls, _item: object) -> type[Self]:
        return cls

    def __init__(self, _uri: str, **_kwargs: object) -> None:
        pass

    @property
    def admin(self) -> Self:
        return self

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def command(self, name: str, *_args: object) -> dict[str, Any]:
        if name == type(self).permanent_error_on:
            raise OperationFailure("permanent MongoDB error")
        if name == "ping":
            type(self).ping_attempts += 1
            if type(self).always_fail_ping or type(self).ping_attempts < 3:
                raise AutoReconnect("server still starting")
            return {}
        if name == "hello":
            type(self).hello_attempts += 1
            if type(self).hello_attempts == 1:
                raise AutoReconnect("election in progress")
            return {"isWritablePrimary": True}
        return {}


class _FakeContainer:
    __slots__ = ()

    def __init__(self, _image: str) -> None:
        pass

    def with_command(self, _command: object) -> Self:
        return self

    def with_exposed_ports(self, _port: int) -> Self:
        return self

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    @staticmethod
    def get_container_host_ip() -> str:
        return "localhost"

    @staticmethod
    def get_exposed_port(_port: int) -> int:
        return 32769


@pytest.fixture
def delayed_mongodb_uri(monkeypatch: pytest.MonkeyPatch) -> Iterator[Iterator[str]]:
    _DelayedMongoClient.ping_attempts = 0
    _DelayedMongoClient.hello_attempts = 0
    _DelayedMongoClient.always_fail_ping = False
    _DelayedMongoClient.permanent_error_on = None
    monkeypatch.setattr(project_fixtures, "DockerContainer", _FakeContainer)
    monkeypatch.setattr(project_fixtures, "MongoClient", _DelayedMongoClient)
    monkeypatch.setattr(project_fixtures, "sleep", lambda _seconds: None)
    uri_iterator = cast("Any", project_fixtures.mongodb_uri).__wrapped__()
    yield uri_iterator
    uri_iterator.close()


def test_mongodb_fixture_waits_for_ping_and_primary(
    delayed_mongodb_uri: Iterator[str],
) -> None:
    assert (
        next(delayed_mongodb_uri) == "mongodb://localhost:32769/?directConnection=true"
    )
    assert _DelayedMongoClient.ping_attempts == 3
    assert _DelayedMongoClient.hello_attempts == 2


@pytest.mark.parametrize("command", ["ping", "hello"])
def test_mongodb_fixture_propagates_permanent_errors(
    delayed_mongodb_uri: Iterator[str], command: str
) -> None:
    _DelayedMongoClient.permanent_error_on = command
    with pytest.raises(OperationFailure, match="permanent MongoDB error"):
        next(delayed_mongodb_uri)


def test_mongodb_fixture_reports_unreachable_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _DelayedMongoClient.ping_attempts = 0
    _DelayedMongoClient.always_fail_ping = True
    clock_readings = iter((0.0, 0.5, 2.0))
    monkeypatch.setattr(project_fixtures, "monotonic", lambda: next(clock_readings))
    monkeypatch.setattr(project_fixtures, "sleep", lambda _seconds: None)
    monkeypatch.setattr(project_fixtures, "_MONGODB_STARTUP_TIMEOUT_SECONDS", 1.0)
    with pytest.raises(pytest.fail.Exception, match="did not become reachable"):
        project_fixtures._wait_for_mongodb_ping(
            cast("MongoClient[dict[str, Any]]", _DelayedMongoClient("mongodb://stub"))
        )
    assert _DelayedMongoClient.ping_attempts == 1
