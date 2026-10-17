# Shared identity-read workload

The reproducible harness in [`benchmarks/public_shared_cache.py`](https://github.com/alessio-locatelli/client-query-cache/blob/main/benchmarks/public_shared_cache.py) measures the public APIs against direct majority reads and independent process-local caches. It starts a disposable MongoDB replica set and four spawned workers, using 4,096 hot identities and approximately 4 KiB documents. Cold windows use distinct seeded identities per worker.

Each of three repetitions rotates path order. Workers warm before a shared start barrier; memory is sampled with managers and mappings still attached. Each worker completes 2,000 measured reads per window. Latency measures each read; CPU is recorded both during the measured reads and including warmup and owner startup, and proportional set size (PSS) apportions shared pages. The shared owner uses a 32 MiB cache budget, 40 MiB arena and 16,384 slots; independent managers use their default 64 MiB budget each. The hot set fits both configurations. Cold-window memory also reflects their different retention budgets. These finite windows describe this workload, rather than establish a universal P99 guarantee or general research qualification.

## Release measurements

Measured on 2026-10-15 using the installed 0.8.0 portable wheel, CPython 3.14.7, an Intel Core i3-13100 with eight logical CPUs, Fedora 44 with Linux kernel 7.2.9 and glibc 2.43. MongoDB used the repository's pinned `mongo:9.0.2` image in a disposable replica set limited to two CPUs and 1 GiB. Tests and builds were stopped during measurement. Results below are medians of the three window statistics; each window contains 8,000 reads across four workers. CPU and PSS sum the workers and shared owner, excluding MongoDB and the harness parent.

### Hot reads

| Model | Path        | Median µs | P95 µs | P99 µs | Measured CPU seconds | Total PSS MiB |
| ----- | ----------- | --------: | -----: | -----: | -------------------: | ------------: |
| Sync  | Direct      |    157.12 | 205.08 | 248.18 |                 0.87 |         158.8 |
| Sync  | Independent |     16.78 |  36.82 |  39.14 |                 0.20 |         232.2 |
| Sync  | Shared      |     26.30 |  65.56 |  74.43 |                 0.29 |         230.0 |
| Async | Direct      |    233.57 | 299.75 | 353.96 |                 1.67 |         160.2 |
| Async | Independent |     17.07 |  38.19 |  40.60 |                 0.18 |         233.7 |
| Async | Shared      |     16.27 |  18.27 |  20.40 |                 0.12 |         231.7 |

Every shared hot window recorded 8,000 shared hits. Shared median latency was about 83% lower than direct reads for sync and 93% lower for async. Across repetitions, shared window medians ranged from 25.2–29.7 µs sync and 9.8–16.3 µs async; independent sync medians varied from 16.1–35.4 µs.

Independent sync caches were faster. Async hot medians were close in this run, with substantial variation across shared repetitions; these finite windows do not establish a general hot-read advantage over independent caches. Sharing reduced active database streams from four to one; direct reads used none. Total PSS includes the shared owner, about 51 MiB in hot windows. At this worker count and working-set size, removing duplicate documents mostly pays for that additional process: combined worker and owner memory is nearly equal. CPU including warmup and owner startup was 3.88 seconds sync and 6.13 seconds async for sharing, versus 3.38 and 5.13 seconds for independent caches.

### Cold reads

| Model | Path        | Median µs | P95 µs |  P99 µs | Measured CPU seconds | Total PSS MiB |
| ----- | ----------- | --------: | -----: | ------: | -------------------: | ------------: |
| Sync  | Direct      |    159.91 | 208.03 |  263.00 |                 0.88 |         158.8 |
| Sync  | Independent |    245.59 | 323.70 |  450.83 |                 1.57 |         269.2 |
| Sync  | Shared      |    216.59 | 356.50 |  675.56 |                 1.89 |         258.5 |
| Async | Direct      |    235.09 | 304.27 |  383.06 |                 1.68 |         160.2 |
| Async | Independent |    333.99 | 420.01 |  531.39 |                 2.44 |         270.7 |
| Async | Shared      |    319.62 | 519.13 | 1248.62 |                 3.00 |         261.2 |

Shared cold windows recorded zero hits. Their median was below independent caches, but CPU and P99 were higher. Admission work and background publication add cost to MongoDB reads; the owner occupied about 77–78 MiB in these windows. CPU including warmup and owner startup was 5.41 seconds sync and 8.81 seconds async, versus 4.67 and 7.37 seconds for independent caches. These results support using sharing for a reused identity hot set; measure miss-heavy applications before opting in. These are 0.8.0 measurements. Subsequent cold-miss work is recorded in [issue #272](https://github.com/alessio-locatelli/client-query-cache/issues/272); it does not replace this dated public-API comparison.

Native implementation and profile attribution are in the [maintainer reference](https://github.com/alessio-locatelli/client-query-cache/blob/main/docs/development/shared-cache.md#profile-attribution-for-the-public-release-workload).

## Reproduce

To run this workload against the current checkout, build its wheel with `just build`, then run the installed artifact:

```bash
uv run --isolated --no-project \
  --python 3.14.7 \
  --with dist/client_query_cache-0.8.1-cp314-abi3-manylinux_2_28_x86_64.whl \
  --with psutil --with testcontainers --with requests --with pyyaml \
  python -m benchmarks.public_shared_cache \
  --output /tmp/agents/shared-cache-performance.json
```

This measures the current 0.8.1 checkout, not the recorded 0.8.0 artifact. For that revision, use the `v0.8.0` checkout and its matching wheel filename.

The command requires a working Docker-compatible development runtime. Use the repository's documented [development environment](https://github.com/alessio-locatelli/client-query-cache/blob/main/CONTRIBUTING.md) when running in Toolbx. The harness accepts no production URI and writes only to its disposable replica set. Raw timing output is untracked.
