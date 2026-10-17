# Stream cost benchmark reports

Use these measurements to understand the cost of process-local caching and MongoDB change streams. For cross-process sharing, use the [shared-cache measurements](shared-cache.md). Start with [workload evaluation](index.md) before running a benchmark.

## Reports

The [retained workload matrix](https://github.com/alessio-locatelli/client-query-cache/tree/main/reports/stream-cost/v1/) covers idle, read-heavy, balanced and write-dominant workloads at small, medium and large document sizes. Reports identify their revision, versions, workload and resource limits, and separate hit, miss, bypass and direct-read latency. Their sampled reads and writes run in separate phases; they do not measure concurrent traffic. For concurrent writes across workers, use the [separate study](index.md#multiple-workers-with-concurrent-writes).

A hit avoids a database round trip. Misses add admission work; writes add invalidation work. Compare CPU, memory, network traffic and tail latency alongside hits, using matching workloads and environments. A smaller latency number alone does not establish lower total cost.

### Change-stream resource cost

In the balanced workloads, cached paths used about 5–26% more MongoDB CPU than direct paths. Received-byte differences ranged from about 57% more for small documents to 94% fewer for large documents. Reusing a large document can avoid more traffic than the stream adds; that does not establish the same savings for small documents or frequent misses.

The reports' `change_stream_cost_comparison` separates raw and cached runs on disposable collections. Dedicated-path bytes exclude unrelated network traffic. Logical event bytes describe decoded event sizes, and `stream_polls` counts manager iteration calls, not wire-level `getMore` commands. See [measurement definitions and protocols](https://github.com/alessio-locatelli/client-query-cache/blob/main/docs/development/stream-cost-benchmarks.md) for exact accounting.

### Change-stream await time

Process-local managers default to a **1,000 ms** maximum idle stream wait. The [recorded comparison](https://github.com/alessio-locatelli/client-query-cache/blob/main/reports/stream-cost/await-v1/summary.md) did not qualify any larger setting: incomplete paired comparisons left the active invalidation-lag requirement unresolved. That is inconclusive evidence, not proof that every larger wait is slower.

The wait bounds an idle server poll, not invalidation latency or network-failure detection. See the [API option and timeout interaction](../reference/api.md#change-stream-await-time) before overriding it. The public shared server uses a separate fixed 100 ms wait and exposes no override.

### Wire compression

The [compression comparison](https://github.com/alessio-locatelli/client-query-cache/blob/main/reports/stream-cost/compression-v1/wire-compression.report.v1.decision.json) measured Snappy, zlib and Zstandard against no compression. All saved bytes on that host; none met every registered CPU and invalidation-lag criterion. The study supports no universal compressor recommendation.

Compression belongs to your PyMongo client and affects all its operations. Use [PyMongo's compression guidance](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/connect/connection-options/network-compression/) and measure your document sizes and network conditions before changing it.

## Reproduce

From a repository checkout with the [development prerequisites](https://github.com/alessio-locatelli/client-query-cache/blob/main/CONTRIBUTING.md), run against the runner's disposable replica set:

```console
uv run -- python -m benchmarks.stream_cost.run --output-dir benchmark-reports
```

Optional `--direct-path-proxy` measures bytes on the dedicated client/container path. Keep raw outputs untracked. The [maintainer protocols](https://github.com/alessio-locatelli/client-query-cache/blob/main/docs/development/stream-cost-benchmarks.md) contain the decision-evidence, await-time and compression commands, statistical gates and environment limits. The await-time matrix takes roughly three hours on the recorded host; inspect existing evidence before rerunning it.

The manual **Stream cost benchmark** GitHub Actions workflow also produces a `stream-cost-reports` artifact for its selected revision. Compare matching rows across comparable runs; timing variation is evidence to investigate, while setup and report-validation errors fail the workflow.
