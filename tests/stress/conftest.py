from __future__ import annotations

from typing import TYPE_CHECKING, NewType

import pytest

if TYPE_CHECKING:
    from _pytest.config.argparsing import Parser

CycleCount = NewType("CycleCount", int)


def pytest_addoption(parser: Parser) -> None:
    parser.addoption(
        "--stress-cycles",
        type=int,
        default=2,
        help="CRUD cycles per mixed-concurrency test (default: 2)",
    )


@pytest.fixture
def stress_cycles(request: pytest.FixtureRequest) -> CycleCount:
    cycles = request.config.getoption("--stress-cycles")
    if cycles <= 0:  # pragma: no cover (invalid CLI input)
        raise pytest.UsageError("--stress-cycles must be positive")
    return CycleCount(cycles)
