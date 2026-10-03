# Stream cost benchmark reports

Start with the [workload evaluation guide](index.md) to choose which comparisons matter for your application.

## Reports

The [initial versioned reports](https://github.com/alessio-locatelli/client-query-cache/tree/main/reports/stream-cost/v1/) cover idle, read-heavy, balanced, and write-dominant workloads at small, medium, and large document sizes. Each JSON file names its workload and records the revision, versions, resource limits, workload parameters, warmup counters, latency distributions, aggregate elapsed time, process CPU, MongoDB container CPU, and logical cache and stream measurements.

The logical `stream_polls` counter counts manager calls to change-stream iteration. One call can issue multiple MongoDB `getMore` commands before returning an event, so this counter cannot measure wire-command traffic. Actual command counts require command-level observation.

Run the same matrix locally with an isolated MongoDB replica set:

```console
uv run -- python -m benchmarks.stream_cost.run --output-dir benchmark-reports
```

The optional `--direct-path-proxy` flag also measures bytes on the dedicated client-to-container path. Those bytes represent only that path. Logical event bytes are decoded event sizes; neither value is a general measure of network traffic.

To reproduce the [decision evidence](https://github.com/alessio-locatelli/client-query-cache/blob/main/reports/stream-cost/v1/decision-evidence.report.v1.json) for the consolidated stream and oversized result on your host, run:

```sh
uv run -- python -m benchmarks.stream_cost.decision_evidence --output decision-evidence.report.v2.json
```

The runner uses the [recorded workload and decision thresholds](https://github.com/alessio-locatelli/client-query-cache/blob/main/reports/stream-cost/v1/decision-pre-registration.json). Compare its outcomes only with a comparable host and topology; the retained report supports decisions for its stated workload.

Choose a workload by the traffic you expect: `idle` for a connected cache with no sampled operations, `read_heavy` for mostly reads, `balanced` for similar read and write counts, or `write_dominant` for mostly writes. Compare only reports with matching workload parameters and comparable environments. Each sampled document is read through the raw path and the cache path in turn, then the sampled writes run as their own phase afterward; a report does not measure interleaved read and write latency. A shared write sample appears in both variant summaries so each summary accounts for the same executed operations.

For example, the [read-heavy, small-document report](https://github.com/alessio-locatelli/client-query-cache/blob/main/reports/stream-cost/v1/read_heavy-small.report.v1.json) describes that exact workload and run. Its latency rows separate raw reads from cache hits, misses, and bypasses. The idle reports explicitly record zero sampled operations and no latency samples. These local reports do not establish a performance conclusion for another host, database, or workload.

### Change-stream resource cost

The [`balanced` reports](https://github.com/alessio-locatelli/client-query-cache/tree/main/reports/stream-cost/v1/) also record a `change_stream_cost_comparison` section: the same workload run once through the raw path (no change stream) and once through the cache path (watching the change stream), each measured on its own disposable collection so the two runs cannot interfere with each other. It presents each path's MongoDB container CPU time side by side, plus a `delta_seconds` field (cache minus raw) and a `delta_percent` field (that delta as a percentage of the raw path's own CPU time, or `null` when the raw path measured zero) — read those fields rather than subtracting or dividing the two numbers yourself. When the report was generated with `--direct-path-proxy`, the section also presents each path's dedicated-connection bytes sent and received side by side, plus a matching `delta` and `delta_percent` (cache minus raw, per direction, and that delta as a percentage of the raw path's own bytes); without that flag, `direct_path_bytes` and its `delta`/`delta_percent` are `null` and `available` is `false`, rather than the section being omitted. The workload's `sample_reads` and `sample_writes` counts (in `workload.parameters`) tell you how many operations that delta covers, so you can also divide it into a per-operation figure yourself.

A raw byte delta alone is not representative across document sizes, so compare the percentage instead. The retained `balanced` reports at each document size illustrate why: the small-document report measured a CPU `delta_percent` of about +24%, and byte deltas of about +57% received / -11% sent; the medium-document report measured about +26% CPU, but -55% received / -11% sent; the large-document report measured about +5% CPU, but -94% received / -11% sent. The received-bytes sign flips as documents grow because the raw path re-fetches the full document on every read, while the cache path fetches it once and serves the rest from memory — for large documents that avoided re-fetching outweighs the stream's own polling traffic, so the cache path receives far _less_, not more.

This grounds two general questions worth asking before trusting the cache with a given workload:

- **Is the library efficient enough to justify the stream's cost?** For a `balanced` (50/50 read/write) shape, yes in these reports: the added CPU cost is real (5-26% of the raw path's own CPU, depending on document size) and each manager pays for a stream per active database (see [capacity estimation](../operations/deployment.md#capacity-estimation)), and larger documents recoup it through avoided re-fetches. Whether it is justified for your workload depends on how many reads that fixed cost gets amortized across — compare the `read_heavy`, `balanced`, and `write_dominant` reports for your document size to see the shape of that trade-off.
- **Can the stream's cost exceed the caching benefit?** Yes, most plausibly for a write-dominant, read-sparse workload: every write still costs an invalidation and a stream event to process, but few reads ever land on a warm entry to recoup that cost. This comparison only measures the `balanced` shape directly; a report does not exist for the `write_dominant` shape's stream-cost delta specifically, so do not assume the same percentages hold — measure your own read/write ratio if it looks closer to write-dominant than balanced.

Like the rest of this capability's measurements, this comparison is evidence to inform investigation, not a pass/fail gate — a `balanced` report captures the cost for its own workload shape and document size, not a universal figure, and a small delta can still flip sign between runs on a noisy host.

The GitHub Actions **Stream cost benchmark** workflow runs when someone starts it from **Actions → Stream cost benchmark → Run workflow** and selects a branch. GitHub calls this a manual `workflow_dispatch`; the workflow must first exist on the repository's default branch. See [GitHub's manual workflow guide](https://docs.github.com/actions/managing-workflow-runs/manually-running-a-workflow).

Run it after a cache or stream change to capture a repeatable report set for that revision. Download the **stream-cost-reports** artifact from the completed run, then compare matching workload and size rows with the retained reports or another run on a comparable runner. Use differences in cache outcomes, latency, CPU, and logical stream activity to choose what to investigate next. Runner performance varies, so timing differences are evidence to inspect rather than an automatic pass/fail threshold; setup and report-validation failures still fail the workflow.

### Change-stream await time

The default is **1,000 ms**. The [measurement summary](https://github.com/alessio-locatelli/client-query-cache/blob/main/reports/stream-cost/await-v1/summary.md) is **inconclusive**:
no larger wait qualified under the frozen rule. All four larger candidates passed the idle byte-savings,
idle process-CPU, and shutdown gates in both execution models, but none passed the async paced-write
invalidation-lag gate.

The run retained 236 measured windows and four explicit failures across 240 planned windows. Write dispatch
exceeded its registered schedule tolerance in the baseline's block 4 synchronous paced and burst windows,
the baseline's block 6 asynchronous burst window, and the 5,000 ms candidate's block 6 synchronous paced
window. These failures leave required paired comparisons unresolved; they do not establish a latency
regression or a performance win. The configured default is the conservative fallback.

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

The isolated single-member replica set uses MongoDB 8.0.4, one CPU, and 512 MiB of memory, with no TLS or wire
compression. Direct-path bytes cover the measured manager's client connections; process CPU includes the
writer, proxy, and observation overhead. Container CPU covers the MongoDB process and its background work.
These measurements do not establish results for sharded clusters, other hosts, or network-failure detection.
See [the manager's await-time option and timeout interaction](../reference/api.md#change-stream-await-time) before
choosing an override.

### Wire compression

The compression benchmark compares no compression against PyMongo's Snappy, zlib, and Zstandard wire compressors on the same isolated replica set, matching an idle window and balanced/write-dominant workloads at small and large document sizes, each with and without the library's change stream watching the traffic. Every mode ran for 4 repeated, counterbalanced blocks so run-order and host noise are visible in the [retained decision evidence](https://github.com/alessio-locatelli/client-query-cache/blob/main/reports/stream-cost/compression-v1/wire-compression.report.v1.decision.json), which records every per-block, per-workload threshold check alongside each mode's median added CPU and stream-path bytes.

None of the three compressors met the pre-registered decision rule on this host: each required, in every one of the 4 blocks and all four active workloads, that the compressor's server CPU and its added CPU over no compression stay within 5% of the uncompressed CPU, its p95 invalidation latency stay within 10%, and its wire bytes fall at least 10%. All three cleared the byte-savings bar comfortably (a median 21%, 33%, and 31% for Snappy, zlib, and Zstandard), but each also broke the CPU and/or p95 invalidation-latency budget in several block/workload combinations, most consistently on the small-document workloads. Snappy's and zlib's idle-window CPU delta against no compression also changed sign from one repeated block to the next — sometimes costing more CPU than no compression, sometimes less; Zstandard's idle delta was consistently positive across all 4 blocks, but it still broke the active-workload CPU or latency budget in every block, so it doesn't qualify either. An idle window still has a small, continuous stream of `getMore` polls from the open change-stream cursor even with no application reads or writes, and compression applies to that polling traffic like any other message; that's what a compressor's idle-window CPU delta is measuring, not some cost from merely having compression configured. The recommendation therefore stays at **no compression**, PyMongo's own default, and is labeled inconclusive rather than a measured win for any mode.

Wire compression is a caller-owned PyMongo client setting, not something `CacheManager` configures: pass `compressors=` (and, for zlib, `zlibCompressionLevel=`) to your own `MongoClient`/`AsyncMongoClient` call, as documented by [PyMongo](https://pymongo.readthedocs.io/) — the setting affects every operation on that client, not only the ones this library serves through the cache.

Reproduce the matrix locally against a fresh isolated replica set:

```console
uv run -- python -m benchmarks.stream_cost.compression_run --output benchmark-reports/wire-compression.report.v1.json --blocks 4
```

The isolated container was limited to 1 CPU and 1 GiB of memory; a busier or larger host may see different — and more or less noisy — results. The reported CPU and byte figures cover only the dedicated benchmark connection the runner measures, and the report's stream-minus-control figures approximate the change stream's own added cost rather than attributing it exactly. As with the rest of this page, treat these numbers as evidence for your own investigation, not a performance guarantee — measure your own workload, document sizes, and host before choosing a non-default compressor.
