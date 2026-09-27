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

The [`balanced` reports](../reports/stream-cost/v1/) also record a `change_stream_cost_comparison` section: the same workload run once through the raw path (no change stream) and once through the cache path (watching the change stream), each measured on its own disposable collection so the two runs cannot interfere with each other. It presents each path's MongoDB container CPU time side by side, so you can see what watching the change stream costs in server CPU under concurrent insert and read traffic. When the report was generated with `--direct-path-proxy`, the section also presents each path's dedicated-connection bytes sent and received side by side; without that flag, it marks the network comparison unavailable rather than omitting it. Each path's numbers cover its whole run — sampled reads and shared writes as well as, on the cache path, the change stream's own polling — so read the _difference_ between the two paths as the change stream's added cost, not either number alone. Like the rest of this capability's measurements, this comparison is evidence to inform investigation, not a pass/fail gate — a `balanced` report captures the cost for its own workload shape and document size, not a universal figure.

The GitHub Actions **Stream cost benchmark** workflow runs when someone starts it from **Actions → Stream cost benchmark → Run workflow** and selects a branch. GitHub calls this a manual `workflow_dispatch`; the workflow must first exist on the repository's default branch. See [GitHub's manual workflow guide](https://docs.github.com/actions/managing-workflow-runs/manually-running-a-workflow).

Run it after a cache or stream change to capture a repeatable report set for that revision. Download the **stream-cost-reports** artifact from the completed run, then compare matching workload and size rows with the retained reports or another run on a comparable runner. Use differences in cache outcomes, latency, CPU, and logical stream activity to choose what to investigate next. Runner performance varies, so timing differences are evidence to inspect rather than an automatic pass/fail threshold; setup and report-validation failures still fail the workflow.

## Pull-request performance guard

Every pull request runs a required **Cache hot-path performance guard** check. It compares the base and proposed revisions on the same runner for a small set of representative operations: cached `find_one` hits (synchronous and asynchronous), bounded `find` admission, and change-event invalidation, each at two document sizes. The check skips its timed comparison, and passes immediately, when a pull request changes no Python code, dependency lockfile, or guard input.

The guard measures repeated, alternating blocks of both revisions and only fails a case when the proposed revision is stably 30% or more slower than the base revision. Ordinary run-to-run noise is reported as an inconclusive warning instead of a failure, so occasional runner variance does not block unrelated work. A missing baseline, an incompatible workload, or another setup problem is reported as a distinct measurement failure rather than a silent pass.

The check's job summary lists, per case, the base and head timings, the relative change, the decision, and both compared revisions. The full result, containing no application documents or credentials, is attached as a downloadable artifact.

This guard covers four representative hot paths on one runner; it does not replace the stream-cost benchmark's controlled matrix or decision evidence described above. Use the manual workflow to investigate a broader cost question or a specific workload.

When a pull request intentionally trades performance for another benefit, the guard still reports the measured slowdown. A maintainer records the accepted cost and its justification during review, then applies the repository's maintainer-only merge exception for that pull request; pull-request authors cannot suppress or bypass the check themselves.
