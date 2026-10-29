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
    assert (
        observations["baseline"]["implementation"]["core"]
        == "client_query_cache._shared_index.LocalCacheCore"
    )
    cold, warm = observations["cold"], observations["warm"]
    assert cold["origins"] - observations["baseline"]["origins"] == 2
    assert warm["origins"] - cold["origins"] == int(scenario == "large-keys")
    assert warm["hits"] - cold["hits"] == int(scenario == "small-entries")
    assert warm["entries"] == int(scenario == "small-entries")
    assert warm["operations"] == 1
    assert warm["p50_ns"] > 0
    assert observations["close"]["entries"] == observations["close"]["aliases"] == 0


@pytest.fixture
async def child_arguments(
    cursors: Binding,
    mongodb_uri: MongoDbUri,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[str, str]:
    view = cursors["view"]
    await resolved(
        view.raw.insert_many(
            [
                {"_id": f"code-{index}", "code": f"C{index:07d}", "state": "active"}
                for index in range(6)
            ]
        )
    )
    monkeypatch.setattr(measure, "DATABASE", view.database.name)
    monkeypatch.setattr(measure, "CODES", view.raw.name)
    monkeypatch.setattr(measure, "COLD_CODES", 4)
    monkeypatch.setattr(measure, "CODE_DOCUMENTS", 6)
    monkeypatch.setitem(measure.BUDGETS, "small-entries", 262144)
    monkeypatch.setattr(measure, "MAX_ENTRY_BYTES", 65536)
    return mongodb_uri, "sync" if isinstance(view.raw, Collection) else "async"


@pytest.mark.integration
@pytest.mark.parametrize(
    "cursors",
    [(api, 1, 0, 262144) for api in ("sync", "async")],
    indirect=True,
    ids=["sync", "async"],
)
async def test_the_memory_child_applies_retention_limits_and_counts_origin_queries(
    child_arguments: tuple[str, str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    uri, api = child_arguments
    await measure.child(uri, "small-entries", api, "cached", limits={"max_entries": 2})
    frames = measure.completed_frames(
        capsys.readouterr().out.encode(), Path("child.jsonl")
    )
    observations = {frame["phase"]: frame for frame in frames}
    baseline, cold, warm = (observations[name] for name in ("baseline", "cold", "warm"))
    assert cold["origins"] - baseline["origins"] == 4
    assert cold["entries"] == warm["entries"] == 2
    assert cold["evictions"] == 2
    assert warm["origins"] - cold["origins"] == 4
    assert warm["hits"] == cold["hits"]
    assert observations["close"]["entries"] == 0


@pytest.mark.unit
def test_skewed_reads_are_deterministic_in_range_and_concentrated() -> None:
    indexes = measure.skewed_indexes()
    assert indexes == measure.skewed_indexes()
    assert len(indexes) == sum(count for _, count in measure.SKEWED_PHASES)
    assert all(0 <= index < measure.CODE_DOCUMENTS for index in indexes)
    assert sum(index < 100 for index in indexes) > len(indexes) // 4
