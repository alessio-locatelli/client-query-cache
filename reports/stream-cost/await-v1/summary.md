# Change-stream await-time results

**Default: 1,000 ms. Outcome: inconclusive; no larger candidate qualified.**

## Scope and method

The matrix used six counterbalanced blocks of 1,000, 5,000, 10,000, 30,000, and 60,000 ms with synchronous and asynchronous managers. Idle windows lasted at least 120 seconds and two complete `getMore` waits; active windows scheduled 200 writes each. Inference used nominal 95% paired-block bootstrap bounds, all 46,656 ordered block resamples, and Holm-Bonferroni adjustment over 128 comparisons.

The environment was MongoDB 8.0.4, PyMongo 4.18.1, Python 3.14.6, and client-query-cache 0.1.0 on Linux x86-64/glibc 2.43. The single-member replica set had one CPU and 512 MiB, with no TLS or compression. The client used a direct connection, unset `timeoutMS` and `socketTimeoutMS`, and `serverSelectionTimeoutMS=10000`.

## Decision evidence

All four larger candidates (5,000, 10,000, 30,000, and 60,000 ms) passed the idle byte-savings, idle process-CPU, and shutdown gates in both execution models. None passed the idle server-CPU gate or the async paced-write lag gate, so none qualified. The largest adjusted shutdown p95 upper bound was approximately 3.0 ms, below the 2,000 ms limit.

The rule requires at least 5% idle server-CPU savings or 10% idle byte savings in each model, with idle process CPU within 5% of baseline. Active lag must remain within 10%, active server and process CPU within 5%, and shutdown within 2,000 ms. Passing requires both the threshold-specific upper bound and the Holm-adjusted p-value to pass.

## Missing comparisons and limitations

The run completed 240 planned windows: 236 measurements and four schedule-tolerance failures:

The failed windows were the 1,000 ms synchronous paced and burst workloads in block 4, the 5,000 ms synchronous paced workload in block 6, and the 1,000 ms asynchronous burst workload in block 6 (blocks numbered from one).

Each failure exceeded the registered dispatch tolerance (10 ms paced; 100 ms burst). These windows remain failed rather than being retried or replaced. Required sync active and async burst comparisons are unresolved because their baseline pairs are incomplete. Async paced comparisons also failed the lag gate; the 10,000 and 60,000 ms candidates failed both active CPU gates, and 30,000 ms failed active server CPU.

The result does not establish that a larger wait causes a latency regression or that 1,000 ms is optimal. Idle byte savings alone cannot satisfy the complete rule. These results cover the tested host and replica set, not sharded clusters or network-failure detection. Process CPU includes the writer, proxy, and observation overhead; bytes cover the measured manager client path.

## Provenance and reproduction

Measurements were taken at revision `505a069`. The frozen expanded input SHA-256 was `d4797f8d8d10c71f4b41d83dfcc51486c1923e47b1f0704133fd6854861a9fc9`. <!-- pragma: allowlist secret -->

The [compact configuration](config.v1.json) expands to the same schedules, comparison family, and limits; its representation has a separate content hash. Raw observations and bootstrap distributions are regenerable local outputs and are not committed.

From the repository root, with the [benchmark prerequisites](../../../CONTRIBUTING.md):

```console
uv run -- python -m benchmarks.stream_cost.await_run --output benchmark-reports/await.report.v1.json
uv run -- python -m benchmarks.stream_cost.await_run --output benchmark-reports/await.report.v1.json --validate-only
```

Use a new output path and allow roughly three hours. The second command validates the raw report and recomputes its decision. Reproduction preserves the protocol; measurements can differ on another run or host.
