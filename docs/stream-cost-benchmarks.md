# Stream cost benchmark reports

## Is caching a good fit for your workload?

Before enabling the cache for a workload, weigh these factors — each is covered by the retained reports below or by
[the architecture doc](architecture.md):

- **Read/write ratio.** Caching benefits read-heavy and balanced workloads the most; a write-dominant workload pays
  the cost of processing a change-stream event and invalidating cache entries on every write, while a shrinking
  share of reads ever reach a warm entry before it's invalidated again. Compare the `read_heavy`, `balanced`, and
  `write_dominant` reports below for a sense of the difference.
- **Topology and process model.** Caching a database costs one change-stream cursor per active database per
  `CacheManager` instance (see [capacity estimation](architecture.md#capacity-estimation)); a high-fan-out or
  short-lived-process deployment, or a manager watching many databases, pays that fixed cost more often or more
  times over, which can outweigh the benefit for that deployment shape even when the read/write ratio looks
  favorable.
- **Document size.** Larger documents cost more to admit and encode into the cache and are more likely to exceed
  `max_entry_bytes` and bypass entirely. Compare the small/medium/large report variants for a workload with a
  document size similar to yours.
- **Stream health.** Caching only helps while a database's change stream is healthy; a database with frequent
  network interruptions, or a MongoDB server or topology that can't provide change streams at all (see
  [system requirements](architecture.md#system-requirements)), bypasses the cache for that traffic instead of
  raising an error.

None of the reports below establishes a performance guarantee for your own workload, host, or MongoDB topology —
use them to decide what to measure on your own deployment before relying on the cache in production.

## Reports

The [initial versioned reports](../reports/stream-cost/v1/) cover idle, read-heavy, balanced, and write-dominant workloads at small, medium, and large document sizes. Each JSON file names its workload and records the revision, versions, resource limits, workload parameters, warmup counters, latency distributions, aggregate elapsed time, process CPU, MongoDB container CPU, and logical cache and stream measurements.

The logical `stream_polls` counter counts manager calls to change-stream iteration. One call can issue multiple MongoDB `getMore` commands before returning an event, so this counter cannot measure wire-command traffic. Actual command counts require command-level observation.

Run the same matrix locally with an isolated MongoDB replica set:

```console
uv run -- python -m benchmarks.stream_cost.run --output-dir benchmark-reports
```

The optional `--direct-path-proxy` flag also measures bytes on the dedicated client-to-container path. Those bytes represent only that path. Logical event bytes are decoded event sizes; neither value is a general measure of network traffic.

To reproduce the [decision evidence](../reports/stream-cost/v1/decision-evidence.report.v1.json) for the consolidated stream and oversized result on your host, run:

```sh
uv run -- python -m benchmarks.stream_cost.decision_evidence --output decision-evidence.report.v2.json
```

The runner uses the [recorded workload and decision thresholds](../reports/stream-cost/v1/decision-pre-registration.json). Compare its outcomes only with a comparable host and topology; the retained report supports decisions for its stated workload.

Choose a workload by the traffic you expect: `idle` for a connected cache with no sampled operations, `read_heavy` for mostly reads, `balanced` for similar read and write counts, or `write_dominant` for mostly writes. Compare only reports with matching workload parameters and comparable environments. Each sampled document is read through the raw path and the cache path in turn, then the sampled writes run as their own phase afterward; a report does not measure interleaved read and write latency. A shared write sample appears in both variant summaries so each summary accounts for the same executed operations.

For example, the [read-heavy, small-document report](../reports/stream-cost/v1/read_heavy-small.report.v1.json) describes that exact workload and run. Its latency rows separate raw reads from cache hits, misses, and bypasses. The idle reports explicitly record zero sampled operations and no latency samples. These local reports do not establish a performance conclusion for another host, database, or workload.

### Change-stream resource cost

The [`balanced` reports](../reports/stream-cost/v1/) also record a `change_stream_cost_comparison` section: the same workload run once through the raw path (no change stream) and once through the cache path (watching the change stream), each measured on its own disposable collection so the two runs cannot interfere with each other. It presents each path's MongoDB container CPU time side by side, plus a `delta_seconds` field (cache minus raw) and a `delta_percent` field (that delta as a percentage of the raw path's own CPU time, or `null` when the raw path measured zero) — read those fields rather than subtracting or dividing the two numbers yourself. When the report was generated with `--direct-path-proxy`, the section also presents each path's dedicated-connection bytes sent and received side by side, plus a matching `delta` and `delta_percent` (cache minus raw, per direction, and that delta as a percentage of the raw path's own bytes); without that flag, `direct_path_bytes` and its `delta`/`delta_percent` are `null` and `available` is `false`, rather than the section being omitted. The workload's `sample_reads` and `sample_writes` counts (in `workload.parameters`) tell you how many operations that delta covers, so you can also divide it into a per-operation figure yourself.

A raw byte delta alone is not representative across document sizes, so compare the percentage instead. The retained `balanced` reports at each document size illustrate why: the small-document report measured a CPU `delta_percent` of about +24%, and byte deltas of about +57% received / -11% sent; the medium-document report measured about +26% CPU, but -55% received / -11% sent; the large-document report measured about +5% CPU, but -94% received / -11% sent. The received-bytes sign flips as documents grow because the raw path re-fetches the full document on every read, while the cache path fetches it once and serves the rest from memory — for large documents that avoided re-fetching outweighs the stream's own polling traffic, so the cache path receives far _less_, not more.

This grounds two general questions worth asking before trusting the cache with a given workload:

- **Is the library efficient enough to justify the stream's cost?** For a `balanced` (50/50 read/write) shape, yes in these reports: the added CPU cost is real (5-26% of the raw path's own CPU, depending on document size) but it is a fixed cost per database per `CacheManager` (see [capacity estimation](architecture.md#capacity-estimation)), and larger documents recoup it through avoided re-fetches. Whether it is justified for your workload depends on how many reads that fixed cost gets amortized across — compare the `read_heavy`, `balanced`, and `write_dominant` reports for your document size to see the shape of that trade-off.
- **Can the stream's cost exceed the caching benefit?** Yes, most plausibly for a write-dominant, read-sparse workload: every write still costs an invalidation and a stream event to process, but few reads ever land on a warm entry to recoup that cost. This comparison only measures the `balanced` shape directly; a report does not exist for the `write_dominant` shape's stream-cost delta specifically, so do not assume the same percentages hold — measure your own read/write ratio if it looks closer to write-dominant than balanced.

Like the rest of this capability's measurements, this comparison is evidence to inform investigation, not a pass/fail gate — a `balanced` report captures the cost for its own workload shape and document size, not a universal figure, and a small delta can still flip sign between runs on a noisy host.

The GitHub Actions **Stream cost benchmark** workflow runs when someone starts it from **Actions → Stream cost benchmark → Run workflow** and selects a branch. GitHub calls this a manual `workflow_dispatch`; the workflow must first exist on the repository's default branch. See [GitHub's manual workflow guide](https://docs.github.com/actions/managing-workflow-runs/manually-running-a-workflow).

Run it after a cache or stream change to capture a repeatable report set for that revision. Download the **stream-cost-reports** artifact from the completed run, then compare matching workload and size rows with the retained reports or another run on a comparable runner. Use differences in cache outcomes, latency, CPU, and logical stream activity to choose what to investigate next. Runner performance varies, so timing differences are evidence to inspect rather than an automatic pass/fail threshold; setup and report-validation failures still fail the workflow.

### Wire compression

The compression benchmark compares no compression against PyMongo's Snappy, zlib, and Zstandard wire compressors on the same isolated replica set, matching an idle window and balanced/write-dominant workloads at small and large document sizes, each with and without the library's change stream watching the traffic. Every mode ran for 4 repeated, counterbalanced blocks so run-order and host noise are visible in the [retained decision evidence](../reports/stream-cost/compression-v1/wire-compression.report.v1.decision.json), which records every per-block, per-workload threshold check alongside each mode's median added CPU and stream-path bytes.

None of the three compressors met the pre-registered decision rule on this host: each required, in every one of the 4 blocks and all four active workloads, that the compressor's server CPU and its added CPU over no compression stay within 5% of the uncompressed CPU, its p95 invalidation latency stay within 10%, and its wire bytes fall at least 10%. All three cleared the byte-savings bar comfortably (a median 21%, 33%, and 31% for Snappy, zlib, and Zstandard), but each also broke the CPU and/or p95 invalidation-latency budget in several block/workload combinations, most consistently on the small-document workloads. Snappy's and zlib's idle-window CPU delta against no compression also changed sign from one repeated block to the next — sometimes costing more CPU than no compression, sometimes less; Zstandard's idle delta was consistently positive across all 4 blocks, but it still broke the active-workload CPU or latency budget in every block, so it doesn't qualify either. An idle window still has a small, continuous stream of `getMore` polls from the open change-stream cursor even with no application reads or writes, and compression applies to that polling traffic like any other message; that's what a compressor's idle-window CPU delta is measuring, not some cost from merely having compression configured. The recommendation therefore stays at **no compression**, PyMongo's own default, and is labeled inconclusive rather than a measured win for any mode.

Wire compression is a caller-owned PyMongo client setting, not something `CacheManager` configures: pass `compressors=` (and, for zlib, `zlibCompressionLevel=`) to your own `MongoClient`/`AsyncMongoClient` call, as documented by [PyMongo](https://pymongo.readthedocs.io/) — the setting affects every operation on that client, not only the ones this library serves through the cache.

Reproduce the matrix locally against a fresh isolated replica set:

```console
uv run -- python -m benchmarks.stream_cost.compression_run --output benchmark-reports/wire-compression.report.v1.json --blocks 4
```

The isolated container was limited to 1 CPU and 1 GiB of memory; a busier or larger host may see different — and more or less noisy — results. The reported CPU and byte figures cover only the dedicated benchmark connection the runner measures, and the report's stream-minus-control figures approximate the change stream's own added cost rather than attributing it exactly. As with the rest of this page, treat these numbers as evidence for your own investigation, not a performance guarantee — measure your own workload, document sizes, and host before choosing a non-default compressor.

## Pull-request performance guard

Every pull request runs a required **Cache hot-path performance guard** check. It compares the base and proposed revisions on the same runner for a small set of representative operations: cached `find_one` hits (synchronous and asynchronous), bounded `find` admission, and change-event invalidation, each at two document sizes. The check skips its timed comparison, and passes immediately, when a pull request changes no Python code, dependency lockfile, or guard input.

The guard measures repeated, alternating blocks of both revisions and only fails a case when the proposed revision is stably 30% or more slower than the base revision. Ordinary run-to-run noise is reported as an inconclusive warning instead of a failure, so occasional runner variance does not block unrelated work. A missing baseline, an incompatible workload, or another setup problem is reported as a distinct measurement failure rather than a silent pass.

The check's job summary lists, per case, the base and head timings, the relative change, the decision, and both compared revisions. The full result, containing no application documents or credentials, is attached as a downloadable artifact.

This guard covers four representative hot paths on one runner; it does not replace the stream-cost benchmark's controlled matrix or decision evidence described above. Use the manual workflow to investigate a broader cost question or a specific workload.

When a pull request intentionally trades performance for another benefit, the guard still reports the measured slowdown. A maintainer records the accepted cost and its justification during review, then applies the repository's maintainer-only merge exception for that pull request; pull-request authors cannot suppress or bypass the check themselves.
