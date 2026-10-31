from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pymongo.synchronous.collection import Collection

from research.process_memory import measure
from tests.cursor_helpers import resolved

if TYPE_CHECKING:
    from tests.conftest import MongoDbUri
    from tests.cursor_fixtures import Binding


@pytest.mark.unit
@pytest.mark.parametrize(
    ("frames", "error"),
    [
        ([], "missing child completion"),
        ([{"phase": "cold"}], "missing child completion"),
        (
            [{"phase": "cold"}, {"completed_phases": ["cold", "close"]}],
            "incomplete child checkpoint",
        ),
        ([{"phase": "cold"}, {"completed_phases": ["cold"]}], None),
    ],
)
def test_acquisition_requires_an_exact_completion_record(
    frames: list[dict[str, object]],
    error: str | None,
) -> None:
    output = "\n".join(json.dumps(frame) for frame in frames).encode()
    if error is None:
        assert measure.completed_frames(output, Path("child.jsonl")) == frames[:-1]
    else:
        with pytest.raises(RuntimeError, match=error):
            measure.completed_frames(output, Path("child.jsonl"))


@pytest.fixture
async def memory_arguments(
    cursors: Binding,
    mongodb_uri: MongoDbUri,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> Namespace:
    view = cursors["view"]
    await resolved(
        view.raw.insert_many(
            [
                {"_id": f"code-{index}", "code": f"C{index:07d}", "state": "active"}
                for index in range(2)
            ]
        )
    )
    monkeypatch.setattr(measure, "DATABASE", view.database.name)
    monkeypatch.setattr(measure, "CODES", view.raw.name)
    return Namespace(
        uri=mongodb_uri,
        api="sync" if isinstance(view.raw, Collection) else "async",
        scenario=scenario,
        budget=262144,
        budget_field="budget_bytes",
        max_entries=1,
        max_key_bytes=2048,
        prefill=0,
        single_identity=False,
        distinct=2,
        retained=1,
        warm_repeats=1,
        unique=False,
    )


@pytest.mark.integration
@pytest.mark.parametrize("scenario", ["small-entries", "large-keys"])
@pytest.mark.parametrize(
    "cursors",
    [(api, 1, 0, 262144) for api in ("sync", "async")],
    indirect=True,
    ids=["sync", "async"],
)
async def test_retention_harness_observes_actual_cache_and_origin_paths(
    memory_arguments: Namespace,
    capsys: pytest.CaptureFixture[str],
    scenario: str,
) -> None:
    await measure.retention_child(memory_arguments)
    frames = measure.completed_frames(
        capsys.readouterr().out.encode(), Path("child.jsonl")
    )
    observations = {frame["phase"]: frame for frame in frames}
    cold, warm = observations["cold"], observations["warm"]
    assert cold["origins"] - observations["baseline"]["origins"] == 2
    assert warm["origins"] - cold["origins"] == int(scenario == "large-keys")
    assert warm["hits"] - cold["hits"] == int(scenario == "small-entries")
    assert warm["entries"] == int(scenario == "small-entries")
    assert warm["operations"] == 1
    assert warm["p50_ns"] > 0
    assert observations["close"]["entries"] == observations["close"]["aliases"] == 0
