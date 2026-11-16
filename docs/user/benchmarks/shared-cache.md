# Shared-cache workloads

The [collection-read comparison](https://github.com/alessio-locatelli/client-query-cache/blob/main/reports/shared-worker-cache/collection-reads.md) covers filtered reads, aggregation, counts and distinct values, including cold misses, larger results and concurrent writes.

## Identity-read workload

The reproducible harness in [`benchmarks/public_shared_cache.py`](https://github.com/alessio-locatelli/client-query-cache/blob/main/benchmarks/public_shared_cache.py) measures the public APIs against direct majority reads and independent process-local caches. It starts a disposable MongoDB replica set and four spawned workers, using 4,096 hot identities and approximately 4 KiB documents. Cold windows use distinct seeded identities per worker.

Each of three repetitions rotates path order. Workers warm before a shared start barrier; memory is sampled with managers and mappings still attached. Each worker completes 2,000 measured reads per window. Latency measures each read; CPU is recorded both during the measured reads and including warmup and owner startup, and proportional set size (PSS) apportions shared pages. The shared owner uses a 64 MiB cache budget, 80 MiB arena and 16,384 slots; independent managers use their default 64 MiB budget each. Both the hot set and the combined warm and cold entries fit these configurations. These finite windows describe this workload, rather than establish a universal P99 guarantee or general research qualification.

Shared-path windows record the owner's effective capacities and telemetry setting in `shared_cache_config`; other paths record `null`.

## Release measurements

The recorded 0.8.0 measurements used a 32 MiB shared-cache budget and 40 MiB arena. Cold-window memory reflects that retention limit.

Measured on 2026-10-15 using the installed 0.8.0 portable wheel, CPython 3.14.7, an Intel Core i3-13100 with eight logical CPUs, Fedora 44 with Linux kernel 7.2.9 and glibc 2.43. MongoDB used the repository's pinned `mongo:9.0.2` image in a disposable replica set limited to two CPUs and 1 GiB. Tests and builds were stopped during measurement. Results below are medians of the three window statistics; each window contains 8,000 reads across four workers. CPU and PSS sum the workers and shared owner, excluding MongoDB and the harness parent. The measured CPU columns include worker memory sampling.

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

Shared cold windows recorded zero hits. Their median was below independent caches, but CPU and P99 were higher. Admission work and background publication add cost to MongoDB reads; the owner occupied about 77–78 MiB in these windows. CPU including warmup and owner startup was 5.41 seconds sync and 8.81 seconds async, versus 4.67 and 7.37 seconds for independent caches. These results support using sharing for a reused identity hot set; measure miss-heavy applications before opting in.

These are 0.8.0 measurements. Later studies measured development revisions with their own workloads: the [completed identity study](https://github.com/alessio-locatelli/client-query-cache/blob/main/reports/shared-worker-cache/v15/results.md) tests cold `_id` misses against the direct-read bounds of [issue #272](https://github.com/alessio-locatelli/client-query-cache/issues/272), and the [collection-read comparison](https://github.com/alessio-locatelli/client-query-cache/blob/main/reports/shared-worker-cache/collection-reads.md) includes cold misses for the other shared read methods. Neither is a current-release measurement or a universal latency guarantee, and neither replaces this dated public-API comparison.

Native implementation and profile attribution are in the [maintainer reference](https://github.com/alessio-locatelli/client-query-cache/blob/main/docs/development/shared-cache.md#profile-attribution-for-the-public-release-workload).

## Reproduce

Use a Linux checkout with the [development prerequisites](https://github.com/alessio-locatelli/client-query-cache/blob/main/CONTRIBUTING.md#prerequisites) and a working container runtime:

- **Toolbx or Distrobox with host Podman:** first run `just enable-podman-socket`, as described in [Validate changes](https://github.com/alessio-locatelli/client-query-cache/blob/main/CONTRIBUTING.md#validate-changes). The benchmark recipe connects through the host Podman socket.
- **Directly on Ubuntu or another Linux host with Docker:** start Docker and ensure your account can access its API. The recipe preserves `DOCKER_HOST` when set and otherwise uses the default Docker socket. See [Docker's Linux post-installation guidance](https://docs.docker.com/engine/install/linux-postinstall/) for access configuration.

The benchmark starts and removes its own MongoDB replica set with CPU and memory limits. You do not need `podman compose up` or `docker compose up`. An existing MongoDB server is not used: the workload resets its benchmark database and measures MongoDB-container CPU.

Build the checkout's wheel, then run the installed artifact:

```bash
just build
just benchmark-shared-cache -- \
  --output /tmp/agents/shared-cache-performance.json
```

The recipe selects the wheel for the checkout's version and running architecture, installs it in an isolated environment, and uses the repository's selected Python. Set `UV_PYTHON` to select another supported Python for matched comparisons. This measures the current checkout, not the recorded 0.8.0 artifact. To repeat the 0.8.0 run, follow the [0.8.0 reproduction](https://github.com/alessio-locatelli/client-query-cache/blob/v0.8.0/docs/user/benchmarks/shared-cache.md#reproduce) from a `v0.8.0` checkout.

The asynchronous workers use standard asyncio by default. To compare uvloop, use `just benchmark-shared-cache --async-loop uvloop -- --output /tmp/agents/shared-cache-uvloop.json`, keeping all other settings identical. The recipe installs uvloop when selected. Put harness arguments after `--`. See the [optional uvloop guidance](../getting-started/asyncio.md#optional-uvloop) for the workloads covered by the evidence.

Use `--validate --disable-telemetry` for matched measurements with production-default telemetry settings. Owner and group CPU from this mode may omit queued admission work and cannot establish a CPU saving. For a separate resource comparison, use `--validate --diagnostics` with telemetry enabled: shared cold windows verify completed admissions before sampling final owner CPU and reconcile worker counts afterward. Foreground latency and admission-drain time are reported separately; compare CPU only between runs with matching telemetry and accounting scopes.

The harness accepts no production URI and writes only to its disposable replica set. Raw timing output is untracked.
