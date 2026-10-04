from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Literal

import pytest

from client_query_cache._core.keys import NamespaceId
from tests.stress.helpers import stress_run, wait_until

if TYPE_CHECKING:
    from faker import Faker

    from tests.conftest import MongoDbUri
    from tests.stress.conftest import CycleCount
    from tests.stress.helpers import Mode, ReadShape, Target

pytestmark = [pytest.mark.integration, pytest.mark.timeout(method="thread")]


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_mixed_crud_respects_processed_invalidations(
    mongodb_uri: MongoDbUri,
    mode: Mode,
    faker: Faker,
    stress_cycles: CycleCount,
) -> None:
    async with stress_run(mongodb_uri, mode, faker) as run:
        targets: tuple[Target, ...] = tuple(
            ("hot", identity) for identity in run.hot_ids
        ) + tuple(("cold", identity) for identity in run.cold_ids)
        traffic_targets = targets[:2] * 4 + targets[2:]
        async with run.traffic(traffic_targets) as readers:
            for _ in range(stress_cycles):
                for kind in ("insert", "update", "replace", "delete"):
                    before_reads = tuple(run.background_reads)
                    for target in targets:
                        expected = await run.write(target, kind)
                        await run.checkpoint(target, expected)
                    assert all(not reader.done() for reader in readers)
                    assert all(
                        current - previous >= len(targets)
                        for current, previous in zip(
                            run.background_reads, before_reads, strict=True
                        )
                    )
        assert run.revision == stress_cycles * 40
        assert run.manager.snapshot().hits > 0


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("shape", ["identity", "namespace"])
@pytest.mark.parametrize("interruption", ["invalidation", "recovery"])
async def test_reads_spanning_invalidation_or_recovery_are_not_admitted(
    mongodb_uri: MongoDbUri,
    mode: Mode,
    shape: ReadShape,
    interruption: Literal["invalidation", "recovery"],
    faker: Faker,
) -> None:
    async with stress_run(mongodb_uri, mode, faker) as run:
        target: Target = ("hot", run.hot_ids[1])
        background: Target = ("cold", run.cold_ids[0])
        before_document = await run.write(target, "insert")
        await wait_until(lambda: run.applied(target))
        background_document = await run.write(background, "insert")
        await run.checkpoint(background, background_document)
        started = run.pause_read(target)
        async with run.traffic((background,)), asyncio.TaskGroup() as readers:
            paused = readers.create_task(run.read(target, shape))
            await started.wait()
            if interruption == "recovery":
                recovering = run.lose_history()
                after_document = await run.write(target, "update")
                background_document = await run.write(background, "update")
                await recovering.wait()
                assert not run.manager.cache_core.is_database_available(run.database)
                before = run.manager.snapshot()
                for _ in range(4):
                    assert await run.read(target, shape) == after_document
                    assert await run.read(background, "identity") == background_document
                after = run.manager.snapshot()
                assert after.hits == before.hits
                assert after.entry_count == before.entry_count == 0
                assert after.used_bytes == before.used_bytes == 0
                assert after.bypasses > before.bypasses
                run.release_recovery.set()
                await wait_until(
                    lambda: run.manager.cache_core.is_database_available(run.database)
                )
            else:
                after_document = await run.write(target, "update")
                await wait_until(lambda: run.applied(target))
            namespace_state = run.manager.cache_core._namespace(
                NamespaceId(run.database, target[0])
            )
            indexed_entries = frozenset(namespace_state.entry_index)
            run.release_read.set()
            assert await paused == before_document
            assert frozenset(namespace_state.entry_index) == indexed_entries
            before = run.manager.snapshot()
            assert await run.read(target, shape) == after_document
            assert run.manager.snapshot().misses > before.misses
            before = run.manager.snapshot()
            assert await run.read(target, shape) == after_document
            assert run.manager.snapshot().hits > before.hits
            if interruption == "recovery":
                recovered_document = await run.write(target, "replace")
                await run.checkpoint(target, recovered_document)
