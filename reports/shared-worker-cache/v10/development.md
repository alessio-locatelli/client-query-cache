# Admission-cost development diagnostics

These exploratory measurements select implementation work for [issue #272](https://github.com/alessio-locatelli/client-query-cache/issues/272). They are excluded from the [registered acceptance study](registration.md). The environment is the registered 0.8.0 development installation on the local i3-13100 host. Timing batches ran sequentially without concurrent tests/builds.

## Isolated costs

Five repetitions of 10,000 core admissions with 4 KiB encoded values gave median CPU costs of **18.65 µs before reusable guards and 11.68 µs at guard checkpoint `91afcc6`**. This measures core insertion without the shared publisher or MongoDB; it does not estimate request latency.

Five repetitions of 10,000 native store/release pairs gave:

| Payload | Byte-vector writer µs | Word-copy writer µs |
| ------: | --------------------: | ------------------: |
|   128 B |                  0.30 |                0.18 |
|   4 KiB |                  4.27 |                0.39 |
|  64 KiB |                 65.94 |                3.70 |

The native comparison uses optimized release builds. Both paths include allocation-class lookup and release; the result supports removing the writer's per-byte temporary-vector work. Native boundary/reuse tests and the existing atomic models remain correctness requirements.

## Cold-window diagnostics

Each batch ran three balanced blocks of eight-worker asyncio cold windows with the version 9 workload/rates. Every batch completed all nine windows healthily. The baseline used clean `e5a25f8`; implementation diagnostics used the working source and were explicitly exploratory. The next study must use clean committed sources and fresh baseline calibration.

| Implementation            | Owner CPU µs/miss, block means | P99 delta over direct ms, blocks 1–3 |
| ------------------------- | -----------------------------: | -----------------------------------: |
| Baseline                  |                  223, 236, 218 |                  1.083, 1.325, 0.590 |
| Guards and adaptive polls |                  217, 214, 217 |                  0.934, 1.217, 0.781 |
| Plus native word copies   |                  190, 202, 195 |                  0.871, 0.729, 1.830 |

These sequential batches are not a paired estimate of implementation effects. Owner CPU falls, while cold tails remain variable and include deltas above the 1 ms limit. Three blocks cannot establish the registered bounds or their stability checks. Namespace-slot/state reuse follows these diagnostics; its acceptance remains unmeasured here.

A cProfile diagnostic traced 220,010 generator context-manager creations for 10,000 baseline admissions; reusable guards reduced that count to 60,010 in an early polling prototype. That instrumentation changes execution cost and supplies no latency evidence. A sampling-profiler attempt fell behind its requested rate and was stopped; its output is excluded.

## Reproduce

Use separate clean checkouts of `e5a25f8`, guard checkpoint `91afcc6`, and the candidate revision recorded by the acceptance report. Build native code with `uv run -- maturin develop --release --locked` before timing. Run the following isolated-cost diagnostic in each checkout:

```bash
uv run -- python - <<'PY'
import statistics
import time

from client_query_cache._core.codec import encode_value
from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.manager import CacheCore, CacheCoreConfig
from client_query_cache._shared_index import OwnerIndex

namespace = NamespaceId("diagnostic", "catalogue")
encoded = encode_value({"payload": "x" * 4096})
core_costs = []
for repetition in range(5):
    core = CacheCore(CacheCoreConfig(shared_budget_bytes=96 * 1024 * 1024))
    started = time.process_time()
    for identity in range(10000):
        capture = core.begin_identity_admission(namespace, identity)
        core.admit_identity_encoded(capture, "full", encoded)
    core_costs.append((time.process_time() - started) * 100)
    core.close()
print("core us/admission", statistics.median(core_costs))

for size in (128, 4096, 65536):
    index = OwnerIndex(32768, 134217728, 1, 1, 197, 3000000000)
    payload = b"x" * size
    copy_costs = []
    for repetition in range(5):
        started = time.process_time()
        for iteration in range(10000):
            block = index.store(payload)
            index.release(block)
        copy_costs.append((time.process_time() - started) * 100)
    print(size, "us/store+release", statistics.median(copy_costs))
PY
```

For the cold diagnostic, copy version 9's configuration to `/tmp/agents/`, set `phases.cold.blocks` to three, and retain its other settings. After sourcing `scripts/testcontainers-bridge.sh`, run:

```bash
uv run -- python -m benchmarks.stream_cost.shared_cache.run --phase cold --only async:8 --config <diagnostic-config> --output <new-raw-report>
```

Inspect each block's request P99 difference between `shared-index` and `direct`, and owner `cpu_seconds / completed`. All raw reports, profiles and diagnostic configurations remain untracked. For cProfile, create its output directory first and set `SHARED_CACHE_PROFILE_DIRECTORY` for a separate one-block run.
