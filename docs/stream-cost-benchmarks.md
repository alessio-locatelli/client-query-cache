# Stream cost benchmark reports

The [initial versioned reports](../reports/stream-cost/v1/) cover idle, read-heavy, balanced, and write-dominant workloads at small, medium, and large document sizes. Each JSON file names its workload and records the revision, versions, resource limits, workload parameters, warmup counters, latency distributions, aggregate elapsed time, process CPU, MongoDB container CPU, and logical cache and stream measurements.

Run the same matrix locally with an isolated MongoDB replica set:

```console
uv run -- python -m benchmarks.stream_cost.run --output-dir benchmark-reports
```

The optional `--direct-path-proxy` flag also measures bytes on the dedicated client-to-container path. Those bytes represent only that path. Logical event bytes are decoded event sizes; neither value is a general measure of network traffic.

Choose a workload by the traffic you expect: `idle` for a connected cache with no sampled operations, `read_heavy` for mostly reads, `balanced` for similar read and write counts, or `write_dominant` for mostly writes. Compare only reports with matching workload parameters and comparable environments. The raw and cache reads are sampled as separate phases, followed by a shared write phase; a report does not measure interleaved read and write latency. A shared write sample appears in both variant summaries so each summary accounts for the same executed operations.

For example, the [read-heavy, small-document report](../reports/stream-cost/v1/read_heavy-small.report.v1.json) describes that exact workload and run. Its latency rows separate raw reads from cache hits, misses, and bypasses. The idle reports explicitly record zero sampled operations and no latency samples. These local reports do not establish a performance conclusion for another host, database, or workload.

The GitHub Actions **Stream cost benchmark** workflow runs only when manually dispatched. It uploads JSON reports as an artifact and does not compare timing with a pass/fail threshold.
