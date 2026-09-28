# Design

## Context

See proposal.md - Why. `CacheManager` wraps a caller-owned PyMongo client, so its stream inherits that client's wire setting. The stream projects `_id`, operation type, namespace, document key, destination, and timestamps; it does not request full documents. The local stream-cost suite already provisions a resource-limited MongoDB 8.0 replica set, measures its container CPU, and counts dedicated connection bytes through a TCP proxy. Its proxy currently rejects compression, and its standard matrix fixes compression off. The existing report schema describes a different matrix and must remain interpretable for retained reports.

## Goals / Non-Goals

**Goals:**

- Measure the compressor's effect on the server cost of this library's actual stream, with a no-stream control under each mode.
- Keep server CPU, stream responsiveness, and direct connection bytes separately visible; retain raw repetitions so the recommendation can be checked.
- Give users a documented PyMongo client setting without changing the library's API or their client configuration.

**Non-Goals:**

- A universal compressor recommendation for all MongoDB applications, TLS, sharded deployments, or WAN links.
- Altering the existing cached-read performance guard or its CI gate.
- Attributing every byte or CPU cycle to the change stream alone; the matched path difference is an approximation.

## Decisions

### Use a dedicated compression matrix on the existing isolated topology

Add a separate manual benchmark entry point under `benchmarks/stream_cost/` and reuse the isolated replica set, workload generators, CPU sampler, and byte proxy. Keep the standard matrix and its report schema unchanged. Use one dedicated client per condition, through the proxy with direct connection, no TLS, and no other application clients. Add `python-snappy` to the development dependency group only. PyMongo 4.18.1 uses Python 3.14's `compression.zstd` and built-in zlib; preflight must still fail visibly if either optional standard-library module is unavailable in a particular Python build. Configure exactly one requested compressor per compressed condition, and record zlib's default level `-1`.

Alternatives: Atlas cannot isolate server CPU on the existing M0 benchmark, and its coarse network samples cannot attribute traffic to a short run. A synthetic compression microbenchmark would miss server polling and change delivery. Reusing the existing matrix unchanged would hide compressor and stream interactions.

### Allow opaque compressed traffic through the byte proxy

The proxy already forwards bytes without decoding MongoDB messages. Remove only its compression prohibition; keep rejection of TLS, discovery, and shared connections. Its counters represent TCP payload crossing the dedicated direct path in each direction, including polling, heartbeats, and commands, but exclude TCP/IP framing and other deployment connections. Verify a requested compressor before timed sampling using a large preflight response through that client and the isolated server's per-compressor `serverStatus` counters, queried by a separate uncompressed admin client outside the proxy. Require the requested compressor's server compression counter to advance and other compressors not to advance for that preflight; record the verification result. Fail if the optional Python compressor is missing or negotiation falls back to no compression. Run the same preflight for the no-compression mode and verify no compressor counter advances.

Alternative: parse `OP_COMPRESSED` inside the proxy. That would add wire-format parsing and possible timed overhead to a component that only needs to count bytes. Server counters are sufficient on an isolated single-member replica set, provided the administrative sampler itself uses an uncompressed connection and preflight is outside measured windows.

### Match the stream and no-stream paths within every mode

Use the same seeded document values and fixed operation schedule for each condition. Include (1) an idle window of fixed duration with a healthy open stream, (2) a balanced read/write window, and (3) a write-heavy window, with small and large documents for active windows. Each condition runs once without a cache manager or stream and once with a primed cache manager and exactly one normal database stream. In the cache path, verify stream health, admissions, hits, and expected processed event count before accepting the sample. Reset collections, cache, and stream between windows and prewarm each run before sampling. Precompute write issue offsets so the same schedule is replayed across all modes and paths; reject a run with missed offsets or mismatched operation counts.

Run at least four full blocks on one replica set. Rotate the four mode positions across blocks and reverse the no-stream/stream order on alternate blocks; retain execution order and every window's values. The measured `stream - no-stream` CPU and byte differences approximate stream cost in that mode. Cross-mode comparison uses those differences and the cache path's absolute values, so a compressor's effect on the shared read/write workload is not mistaken for its effect on the stream. A fixed duration and an uncompressed administrative sampler outside timed windows limit contamination. The benchmark is manual because these many controlled windows are too costly for the pull-request guard.

Alternative: one run per mode would be faster but could mistake warm server state or transient host load for a compressor effect. A fresh server for each window would lose a matched topology and add startup variance.

### Report distributions and make the recommendation conservatively

Create a separate versioned compression report schema and retain one aggregate report with metadata plus every raw window. Record container CPU seconds, process CPU seconds, monotonic elapsed time, direct-path bytes sent/received, read and write latency distributions by path/outcome, and local monotonic write-start-to-invalidation-applied latency for cache writes. Use the existing stream-cost snapshot's monotonic invalidation-apply readings, with at most one outstanding invalidation at a time so readings match write order while reads can run concurrently. The latter includes write completion and delivery, so label it as end-to-end invalidation latency; it does not use server `wallTime` and needs no clock-offset assumption. An idle window has no operation latency samples. Include the compressor preflight, MongoDB/Python/PyMongo versions, resource limits, fixed schedules, counts, and limitations. Reject incomplete matrices, bad counter deltas, missing samples, and mismatched workloads before writing a decision.

Pre-register the recommendation rule with the workload configuration, before measurement. A compressed mode qualifies only if, in every paired block and active workload, both its stream-path server CPU and its stream-minus-control CPU delta are no more than 5% of the no-compression stream-path CPU above their respective no-compression values, its p95 end-to-end invalidation latency is no more than 10% above no compression, and its stream-path total direct-path bytes (sent plus received) fall at least 10%. Using the full-path CPU as the additive budget avoids dividing by a near-zero stream delta. These are practical tolerance and benefit thresholds, not statistical confidence bounds. Among qualifying modes, choose the one with the lowest median stream-path total bytes; break a near tie in favor of lower median added server CPU, then no compression. If none qualify, or the idle CPU comparison is too noisy to tell whether compression adds cost, retain no compression and label the result inconclusive where appropriate. Show the per-block values and do not infer behavior on other hosts or deployments.

Alternative: choose solely by compression ratio. That ignores the main server and invalidation costs the user asked to weigh. A formal significance claim from four blocks would imply more precision than these local measurements warrant.

Document the resulting recommendation in `docs/stream-cost-benchmarks.md`, link the retained report, and add a short link or pointer from the README if needed. State that compression is configured on the caller's PyMongo client and affects all of its traffic. Do not set a compressor inside `CacheManager`.

## Risks / Trade-offs

- [Small idle CPU deltas approach host noise] → Retain raw blocks and absolute seconds; use an explicit inconclusive outcome instead of a percentage-only claim.
- [The proxy counts only one direct path] → State its scope and keep TLS, discovery, and shared-connection rejection.
- [Preflight or admin calls pollute a timed window] → Complete verification before sampling and use a separate uncompressed admin connection outside the proxy.
- [Write-to-invalidation latency conflates write and stream delivery] → Label it end-to-end and pair it with the same writes and schedules across modes.
- [A local winner fails on a remote or different workload] → Document the tested MongoDB version, topology, host limits, document sizes, and traffic mix alongside the recommendation.

## Migration Plan

Add the benchmark and its separate report without changing existing retained reports. After a valid local run, publish the versioned report and update performance guidance. Reverting the guidance and benchmark leaves the public library API unchanged.
