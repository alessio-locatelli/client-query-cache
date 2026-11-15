from __future__ import annotations

import asyncio
import pickle  # noqa: S403 - exercise the trusted spawn payload
import sys
from typing import TYPE_CHECKING, Literal

import pytest
import uvloop

from benchmarks import public_shared_cache as harness

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "loop_name", ["asyncio", "uvloop"], ids=["standard", "optional"]
)
def test_worker_uses_the_serialized_loop_selection(
    monkeypatch: pytest.MonkeyPatch, loop_name: Literal["asyncio", "uvloop"]
) -> None:
    observed = harness.Observation([], 0, 0, 0, 0, 0)

    async def measure(window: harness.Window) -> harness.Observation:
        assert window.async_loop == loop_name
        loop = asyncio.get_running_loop()
        assert isinstance(loop, uvloop.Loop) == (loop_name == "uvloop")
        await asyncio.sleep(0)
        return observed

    monkeypatch.setattr(harness, "_measure_async", measure)
    window = harness.Window(
        "unused", "direct", "async", "hot", 0, 1, None, async_loop=loop_name
    )
    restored = pickle.loads(pickle.dumps(window))  # noqa: S301 - local payload
    assert harness._worker(restored) is observed


def test_unavailable_requested_loop_fails_before_database_setup(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    def unavailable(name: str) -> None:
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(harness, "import_module", unavailable)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "public_shared_cache",
            "--async-loop",
            "uvloop",
            "--output",
            str(tmp_path / "unused.json"),
        ],
    )
    with pytest.raises(SystemExit, match="2"):
        harness.main()
    assert "cannot load requested loop uvloop" in capsys.readouterr().err
    assert not (tmp_path / "unused.json").exists()
