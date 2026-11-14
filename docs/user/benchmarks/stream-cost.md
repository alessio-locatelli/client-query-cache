# Stream cost benchmark reports

Use these measurements to understand the cost of process-local caching and MongoDB change streams. For cross-process sharing, use the [shared-cache measurements](shared-cache.md). Start with [workload evaluation](index.md) before running a benchmark.

## Reports

The [historical stream-cost summary](https://github.com/alessio-locatelli/client-query-cache/blob/main/reports/stream-cost/v1/summary.md)
records a phased workload comparison from version 0.1.0. It is not a measurement
of the current release. For concurrent writes across workers, use the
[separate study](index.md#multiple-workers-with-concurrent-writes).

A hit avoids a database round trip. Misses add admission work; writes add invalidation work. Compare CPU, memory, network traffic and tail latency alongside hits, using matching workloads and environments. A smaller latency number alone does not establish lower total cost.

### Change-stream resource cost

The historical balanced workload showed that avoided document fetches can
outweigh polling traffic for larger results while increasing MongoDB CPU.
Its small, sequential read/write sample does not predict current workload costs.
The [measurement record](https://github.com/alessio-locatelli/client-query-cache/blob/main/reports/stream-cost/v1/summary.md#balanced-resource-comparison)
retains the values, environment and limitations.

### Change-stream await time

Process-local managers default to a **1,000 ms** maximum idle stream wait. The [recorded comparison](https://github.com/alessio-locatelli/client-query-cache/blob/main/reports/stream-cost/await-v1/summary.md) did not qualify any larger setting: incomplete paired comparisons left the active invalidation-lag requirement unresolved. That is inconclusive evidence, not proof that every larger wait is slower.

The wait bounds an idle server poll, not invalidation latency or network-failure detection. See the [API option and timeout interaction](../reference/api.md#change-stream-await-time) before overriding it. The public shared server uses a separate fixed 100 ms wait and exposes no override.

### Wire compression

The [compression comparison](https://github.com/alessio-locatelli/client-query-cache/blob/main/reports/stream-cost/compression-v1/summary.md) measured Snappy, zlib and Zstandard against no compression. All saved bytes on that host; none met every registered CPU and invalidation-lag criterion. The study supports no universal compressor recommendation.

Compression belongs to your PyMongo client and affects all its operations. Use [PyMongo's compression guidance](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/connect/connection-options/network-compression/) and measure your document sizes and network conditions before changing it.

## Reproduce

From a repository checkout with the [development prerequisites](https://github.com/alessio-locatelli/client-query-cache/blob/main/CONTRIBUTING.md), run against the runner's disposable replica set:

```console
uv run -- python -m benchmarks.stream_cost.run --output-dir benchmark-reports
```

Optional `--direct-path-proxy` measures bytes on the dedicated client/container path. Repeat `--workload <name>`, for example `--workload read_heavy-small`, to run only those workloads. Keep raw outputs untracked. The [maintainer protocols](https://github.com/alessio-locatelli/client-query-cache/blob/main/docs/development/stream-cost-benchmarks.md) contain the decision-evidence, await-time and compression commands, statistical gates and environment limits. The await-time matrix takes roughly three hours on the recorded host; inspect existing evidence before rerunning it.

The manual **Stream cost benchmark** GitHub Actions workflow also produces a `stream-cost-reports` artifact for its selected revision. Compare matching rows across comparable runs; timing variation is evidence to investigate, while setup and report-validation errors fail the workflow.
