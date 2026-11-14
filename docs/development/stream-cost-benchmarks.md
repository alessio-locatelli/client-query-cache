# Stream-cost benchmark protocols

Start with the [public workload guide](../user/benchmarks/index.md) to choose which comparisons matter for your application.

## Reports

The [historical measurement summary](../../reports/stream-cost/v1/summary.md)
retains the balanced resource comparison and serial-router decision. Raw
benchmark output stays untracked. Generate matched reports for current code.

The version-1 report format retains `measurement.logical_metrics.cache.shared_budget_bytes` as its serialized budget field. The collector fills it from the current `CacheSnapshot.budget_bytes` attribute; the report field is independent of the Python API name.

The logical `stream_polls` counter counts manager calls to change-stream iteration. One call can issue multiple MongoDB `getMore` commands before returning an event, so this counter cannot measure wire-command traffic. Actual command counts require command-level observation.

Run the same matrix locally with an isolated MongoDB replica set:

```console
uv run -- python -m benchmarks.stream_cost.run --output-dir benchmark-reports
```

The optional `--direct-path-proxy` flag also measures bytes on the dedicated client-to-container path. Those bytes represent only that path. Logical event bytes are decoded event sizes; neither value is a general measure of network traffic.

To collect fresh [decision evidence](../../reports/stream-cost/v1/summary.md#consolidated-stream-decision) for the consolidated stream and oversized result on your host, run:

```sh
uv run -- python -m benchmarks.stream_cost.decision_evidence --output /tmp/agents/decision-evidence.json
```

The runner uses the [recorded workload and decision thresholds](https://github.com/alessio-locatelli/client-query-cache/blob/main/reports/stream-cost/v1/decision-pre-registration.json). Compare its outcomes only with a comparable host and topology; the retained report supports decisions for its stated workload.

Choose a workload by the traffic you expect: `idle` for a connected cache with no sampled operations, `read_heavy` for mostly reads, `balanced` for similar read and write counts, or `write_dominant` for mostly writes. Compare only reports with matching workload parameters and comparable environments. Each sampled document is read through the raw path and the cache path in turn, then the sampled writes run as their own phase afterward; a report does not measure interleaved read and write latency. A shared write sample appears in both variant summaries so each summary accounts for the same executed operations.

### Change-stream resource cost

Generated balanced reports record a `change_stream_cost_comparison` section: the same workload run once through the raw path (no change stream) and once through the cache path (watching the change stream), each measured on its own disposable collection so the two runs cannot interfere with each other. It presents each path's MongoDB container CPU time side by side, plus a `delta_seconds` field (cache minus raw) and a `delta_percent` field (that delta as a percentage of the raw path's own CPU time, or `null` when the raw path measured zero) — read those fields rather than subtracting or dividing the two numbers yourself. When the report was generated with `--direct-path-proxy`, the section also presents each path's dedicated-connection bytes sent and received side by side, plus a matching `delta` and `delta_percent` (cache minus raw, per direction, and that delta as a percentage of the raw path's own bytes); without that flag, `direct_path_bytes` and its `delta`/`delta_percent` are `null` and `available` is `false`, rather than the section being omitted. The workload's `sample_reads` and `sample_writes` counts (in `workload.parameters`) tell you how many operations that delta covers, so you can also divide it into a per-operation figure yourself.

The [historical balanced comparison](../../reports/stream-cost/v1/summary.md#balanced-resource-comparison)
illustrates how avoided document fetches can offset stream bytes while MongoDB
CPU still increases. Its short phased workload does not predict concurrent
read/write cost. Compare matching parameters and environments, and measure the
application's actual hit rate, CPU and traffic.

The GitHub Actions **Stream cost benchmark** workflow runs when someone starts it from **Actions → Stream cost benchmark → Run workflow** and selects a branch. GitHub calls this a manual `workflow_dispatch`; the workflow must first exist on the repository's default branch. See [GitHub's manual workflow guide](https://docs.github.com/actions/managing-workflow-runs/manually-running-a-workflow).

Run it after a cache or stream change to capture a repeatable report set for that revision. Download the **stream-cost-reports** artifact from the completed run, then compare matching workload and size rows with another run on a comparable runner. Use differences in cache outcomes, latency, CPU, and logical stream activity to choose what to investigate next. Runner performance varies, so timing differences are evidence to inspect rather than an automatic pass/fail threshold; setup and report-validation failures still fail the workflow.

### Change-stream await time

The default is **1,000 ms**. The [historical summary](../../reports/stream-cost/await-v1/summary.md)
records why no larger candidate qualified and which paired comparisons were
incomplete. The study is inconclusive, not proof that a larger wait is slower.

The await-time benchmark compares 1,000, 5,000, 10,000, 30,000, and 60,000 ms with both synchronous and
asynchronous managers. Its [frozen configuration](https://github.com/alessio-locatelli/client-query-cache/blob/main/reports/stream-cost/await-v1/config.v1.json) specifies six
counterbalanced blocks, fresh manager state for each window, at least 120 seconds and two complete `getMore`
waits per idle window, 200 writes per paced or burst window, and separate in-flight shutdown trials.

Reproduce the matrix from the repository root with the [benchmark prerequisites](https://github.com/alessio-locatelli/client-query-cache/blob/main/CONTRIBUTING.md):

```console
uv run -- python -m benchmarks.stream_cost.await_run --output benchmark-reports/await.report.v1.json
```

Allow roughly three hours on a comparable host. The output path must be new. The runner records actual
`getMore` counts and requested `maxTimeMS` values without retaining command bodies. Its decision file retains
all registered comparisons, paired-block bootstrap distributions, nominal 95% one-sided bounds, and
Holm-Bonferroni adjusted results.
Missing measurements and unstable ratio denominators cannot establish a saving or noninferiority.

A larger wait qualifies only when the adjusted bounds pass every safety gate in both execution models:
active p95 invalidation lag within 10% of the 1,000 ms baseline, active server and process CPU within 5%,
idle process CPU within 5%, and p95 shutdown at most two seconds. It must also save at least 5% idle server
CPU or 10% idle bytes in each model. Among qualifying candidates, selection prefers a decisive idle server
CPU advantage over all others in both models, followed by bytes, and otherwise the shortest wait.
If none qualifies, the default remains 1,000 ms.

Keep generated raw results out of Git. Validate your local report and recompute its decision with:

```console
uv run -- python -m benchmarks.stream_cost.await_run --output benchmark-reports/await.report.v1.json --validate-only
```

The isolated single-member replica set runs the MongoDB server pinned in the repository's [`docker-compose.yaml`](https://github.com/alessio-locatelli/client-query-cache/blob/main/docker-compose.yaml) with one CPU and 512 MiB of memory, and with no TLS or wire
compression. Direct-path bytes cover the measured manager's client connections; process CPU includes the
writer, proxy, and observation overhead. Container CPU covers the MongoDB process and its background work.
These measurements do not establish results for sharded clusters, other hosts, or network-failure detection.
See [the manager's await-time option and timeout interaction](../user/reference/api.md#change-stream-await-time) before
choosing an override.

### Wire compression

The compression benchmark compares uncompressed PyMongo traffic with Snappy,
zlib and Zstandard over repeated idle and active workloads. The
[historical decision](../../reports/stream-cost/compression-v1/summary.md)
qualified no compressor and lacks complete measured-source/host metadata;
it is not a current baseline. Generate fresh paired results before making a
resource recommendation.

Wire compression is a caller-owned PyMongo client setting, not something `CacheManager` configures: pass `compressors=` (and, for zlib, `zlibCompressionLevel=`) to your own `MongoClient`/`AsyncMongoClient` call, as documented by [PyMongo](https://pymongo.readthedocs.io/) — the setting affects every operation on that client, not only the ones this library serves through the cache.

Reproduce the matrix locally against a fresh isolated replica set:

```console
uv run -- python -m benchmarks.stream_cost.compression_run --output benchmark-reports/wire-compression.report.v1.json
```

The default isolated container uses 1 CPU and 1 GiB of memory; a busier or larger host may see different — and more or less noisy — results. The reported CPU and byte figures cover only the dedicated benchmark connection the runner measures, and the report's stream-minus-control figures approximate the change stream's own added cost rather than attributing it exactly. As with the rest of this page, treat these numbers as evidence for your own investigation, not a performance guarantee — measure your own workload, document sizes, and host before choosing a non-default compressor.
