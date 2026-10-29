# ruff: noqa: PLC2701, SLF001 - Measure authoritative core writes and inspect native publication.
import json
import time

from client_query_cache._core.codec import encode_value
from client_query_cache._core.find_reads import FindReadShape
from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.manager import CacheCore, CacheCoreConfig
from client_query_cache._shared.shared_index import ArenaPayloads, IndexPublisher
from client_query_cache._shared_index import OwnerIndex


def main() -> None:
    namespace = NamespaceId("diagnostic", "sorted")
    encoded = encode_value([{"_id": i, "payload": "x" * 4096} for i in range(16)])
    rows = []
    for count, rounds in ((1, 500), (64, 100), (1024, 20)):
        index = OwnerIndex(32768, 128 * 1024 * 1024, 1, 1, 1, 60 * 10**9)
        publisher = IndexPublisher(index, (namespace.database,), 1)
        core = CacheCore(
            CacheCoreConfig(budget_bytes=96 * 1024 * 1024),
            observer=publisher,
            payloads=ArenaPayloads(index),
        )
        publisher.assign(namespace, core.current_epoch(namespace))
        shapes = tuple(
            FindReadShape(("find", category), 16) for category in range(count)
        )
        batches = []
        for _batch in range(5):
            cpu = wall = 0
            for _ in range(rounds):
                capture = core.capture_namespace_generation(namespace)
                for shape in shapes:
                    core.admit_namespace_encoded(
                        capture, shape.discriminator, encoded, find_source=shape.source
                    )
                assert index.published() == count
                cpu_start, wall_start = time.process_time_ns(), time.perf_counter_ns()
                core.record_write(namespace, "external-write")
                wall += time.perf_counter_ns() - wall_start
                cpu += time.process_time_ns() - cpu_start
                assert index.published() == 0
                assert publisher._finds == {}
            batches.append(
                {"cpu_us": cpu / rounds / 1000, "wall_us": wall / rounds / 1000}
            )
        rows.append({"shapes": count, "rounds_per_batch": rounds, "batches": batches})
        core.close()
    print(json.dumps({"encoded_result_bytes": len(encoded), "rows": rows}, indent=2))


if __name__ == "__main__":
    main()
