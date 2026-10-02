# Defer the public causal invalidation barrier

Status: **Accepted — feature deferred.**

Date: 2026-10-02.

## Context

The library caches reads in application memory and invalidates them asynchronously through MongoDB change
streams. Ordinary cached reads can briefly return a value that precedes a completed write. Applications can
choose database reads, using the session and read/write concerns appropriate to their consistency requirements,
for operations requiring freshness. A session-bound read through the cached facade also bypasses caching.
These reads do not refresh the in-memory cache or synchronize other processes.

An explicit barrier could let an application wait for one manager's invalidations before continuing cached
reads. The [investigation](../causal-invalidation-barrier-research.md) found significant latency, resource costs,
and restrictions, without demonstrating that this capability serves the motivating third-party integrations.

## Decision

Keep eventual consistency as the standard cached-read contract. Use database reads wherever freshness is
required. Preserve the existing decision that writes do not populate the cache; see
[Why only reads are cached](../architecture.md#why-only-reads-are-cached).

Defer a public causal invalidation barrier. Reject inclusion of the implementation in
[PR #124](https://github.com/alessio-locatelli/client-query-cache/pull/124), branch
`add-causal-invalidation-barrier`. Preserve its research as reference material, without making its proposed API
or narrowed guarantees part of the supported library contract.

Research into freshness requirements in specific third-party integrations is **deferred and low priority**.
Reconsider it when a concrete application requires freshness through an integration and direct or session-bound
database reads cannot meet that requirement. A new proposal must establish:

- The application's acceptable delay after a write, including idle deployments.
- Which writes must be observed and what session or other causal evidence the integration exposes.
- Whether the guarantee must cover one manager, other managers, or multiple application processes.
- Why database reads do not meet the requirement and why the expected benefit warrants the resource and
  maintenance costs of another mechanism.

The examples' polling demonstrates invalidation. Polling alone does not establish a production need for a
barrier. Reconsideration requires a newly scoped OpenSpec change; the withdrawn runtime plan is not ready work
for another coding agent to apply.

## Alternatives considered

- **Ship the investigated barrier.** It offers explicit catch-up for applications controlling their PyMongo
  writes, but its measured idle waits, per-wait stream cost, and caller-enforced restrictions are a poor default
  for an immediate response path. A justified background-processing use case has not been established.
- **Keep the implementation privately.** This retains concurrency and compatibility maintenance costs without
  an established consumer.
- **Keep only a link to the unmerged work.** This makes discovery depend on branch or PR archaeology. Keeping a
  maintained decision and curated report makes the deferral visible alongside current architecture guidance.

## Consequences and limitations

Applications retain a clear choice between cached reads with eventual invalidation and database reads with
their chosen consistency settings. Immediate read-your-write through ordinary cache hits is not promised, and
no manager synchronizes another manager's memory cache.

The investigation remains available if an application justifies reopening the feature. Its observations require
validation against the future target environment, and its assumptions must be resolved before a new guarantee
is exposed. Independent correctness findings from the investigation are separate from this low-priority
feature deferral; see the report's [timeout-context finding](../causal-invalidation-barrier-research.md#independent-timeout-context-finding).
