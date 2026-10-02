# Design

## Context

See [proposal.md](proposal.md) for motivation. `CacheSnapshot` is immutable, but its type is defined under `_core` and ordinary callers reach it through `CacheCore`. Both collection variants collapse eligibility into booleans; missing collections and inconclusive metadata both become `None`. Core lookup, alias resolution, and admission can also record bypasses. The coordinator discards failed startup supervisors, so an inspection cannot currently distinguish an unstarted database from a failed startup.

`CacheCore.snapshot()` gathers capacity and statistics under separate locks. It is an observation, not an atomic transaction across all cache state. Preserve that property rather than adding a global lock. Existing stream-cost accessors and the optional OpenTelemetry bridge remain useful.

## Goals / Non-Goals

**Goals:** A typed manager inspection surface, deterministic reason classification, safe health inspection, bounded metric cardinality, and equivalent sync/async behavior without network calls during inspection.

**Non-Goals:** Per-query traces, hit-ratio promises, counter resets, stream-position exposure, write catch-up guarantees, or changing which reads cache. Inspection does not activate a stream.

## Decisions

### D1. Delegate public inspection without creating another statistics owner

Both managers expose `snapshot() -> CacheSnapshot`, `stream_health_snapshot(database_name) -> StreamHealthSnapshot`, `stream_cost_snapshot(database_name) -> StreamCostSnapshot`, and `active_stream_cost_databases() -> list[str]`. All four are synchronous even on the asyncio manager because they perform bounded local inspection only. Retain `cache_core` unchanged. Export snapshot types and `BypassReason` through the top-level, synchronous, and asynchronous packages; type imports do not require OpenTelemetry.

Reuse the existing core for cache/stream-cost measurements and the coordinator for health. The health snapshot contains the requested database name and a fixed status: `not_started`, `connecting`, `healthy`, `reconnecting`, `startup_failed`, or `closed`. Closed-manager inspection returns `closed`, and known startup failures remain inspectable until retried or closed. A successful retry replaces failure state. Do not retain exceptions, credentials, raw error messages, timestamps of unrelated operations, or resume tokens in snapshots.

Alternative: rename or remove `CacheCore`. Rejected because an additive manager interface solves ordinary usage without disrupting its documented advanced API. Alternative: await asyncio snapshots. Rejected because inspection owns no asynchronous I/O; follow existing local core inspection semantics.

### D2. Add reasons to the existing recording events

Use a public string-valued enum with these fixed values: `session`, `read_profile`, `unsupported_options`, `unsafe_filter`, `unsafe_projection`, `unsafe_pipeline`, `uncanonicalizable_key`, `missing_collection`, `view_collection`, `time_series_collection`, `metadata_unavailable`, `stream_unavailable`, `admission_invalidated`, and `unspecified`.

Every existing ordinary bypass recording increments the aggregate and exactly one reason under the statistics lock. Oversized recording remains separate and increments no ordinary reason. Keep `CacheCore.record_bypass()` usable without an argument, classifying that public advanced call as `unspecified`; internal call sites supply specific reasons. A generation change while a database is still available is `admission_invalidated`, whereas actual unavailability is `stream_unavailable`.

Add `CacheSnapshot.bypass_reasons` as an immutable tuple of frozen `BypassReasonCount(reason, count)` records in enum order, including zero counts. Export this record type too. Gather the reason tuple and aggregate ordinary count in one statistics-lock acquisition so their sum agrees within a snapshot. Other snapshot fields retain their current independently sampled semantics. Reason space and storage remain constant-sized; no collection-keyed counter registry is introduced.

The counts describe recording events, not mutually exclusive application-request outcomes. An unavailable lookup or a raced admission can coexist with an earlier miss; alias/core paths can record more than one event during a request. Preserve those totals instead of silently changing existing metrics to count requests.

### D3. Preserve eligibility information and choose one reason deterministically

Extract pure classification shared by both collection variants; retain native I/O in each. Evaluate request reasons in this order: session, read profile, unsupported options, unsafe filter/pipeline, unsafe projection, uncanonicalizable key, then collection/stream eligibility. Stop at the first reason. Successful eligible hits add no reason work beyond the eligibility checks already needed.

Extend metadata probing so absence, an inconclusive probe, an ordinary collection, a view, and time-series are distinguishable. Unrecognized collection types fail closed as inconclusive metadata. Preserve retry behavior: absence and inconclusive probes do not become sticky cache-ineligible metadata; conclusive view/time-series results retain their existing epoch-based lifetime. Missing index-discovery permission does not by itself make a generic namespace query unsafe; classify a bypass only where that failure actually prevents the existing selected read path.

Keep public boolean `ensure_cache_eligible` behavior where advanced callers rely on it; introduce an internal classified result instead of changing a boolean's truth semantics. Both manager variants use it for their read views. Store bounded startup-status records alongside the existing coordinator registry, without altering its retry policy.

### D4. Extend the optional metrics bridge through a minimal typed source

Use a structural statistics-source protocol containing `snapshot`, `stream_cost_snapshot`, and `active_stream_cost_databases`. Both managers and `CacheCore` satisfy it. Keep the second positional parameter's name `cache_core` in `register_cache_metrics` so existing keyword calls still work; document manager instances as the ordinary argument.

Keep all existing instrument names and emit a separate `client_query_cache.cache.bypasses.by_reason` observable counter with the fixed attribute `cache.bypass.reason`. Its observations match the ordinary reason counts; oversized bypasses remain on their existing counter. Do not add database, collection, filter, or error text attributes to this manager-wide instrument. Collection callbacks remain read-only. Correct the aggregate counter description to explain accounting events rather than claiming one count per read.

Alternative: add reason attributes to the existing aggregate instrument. Rejected because it changes the identity and aggregation of existing time series. Alternative: logging every bypass. Rejected because hot-loop logging creates avoidable cost and can expose application information.

### D5. Resource costs and evidence

Reason recording adds one indexed integer increment inside an existing lock, with constant memory per manager. Snapshot reason construction is O(R) for the fixed reason count. Health lookup is O(1); health-state storage is O(D), like existing per-database supervision. No inspection makes a database call or creates a supervisor. Metric collection creates O(R + D) observations plus the existing bounded lag-window work.

Measure cached hits, repeated missing-collection bypasses, session/profile bypasses, concurrent recording, snapshots, and metrics collection against the pre-change baseline. Use the existing `benchmarks/stream_cost/guard_workload.py` workloads for hit-path comparison and a narrowly scoped untracked harness for diagnostics paths. Report latency/allocation deltas and the observed bottleneck in the implementation commit body; no measurements are claimed by this planning change. Raw results stay untracked.

## Risks / Trade-offs

- [Reason counters accidentally change totals] -> Map every existing recording site before editing and compare aggregate outcomes for identical operation sequences, including admission races and aliases.
- [Probe refactoring makes absent metadata sticky] -> Retain absence/inconclusive retry tests and add reason assertions without changing eligibility lifetimes.
- [Health inspection races shutdown or startup retry] -> Snapshot state under the existing lifecycle/coordinator synchronization, with no cache lock held while acquiring a coordinator lock.
- [An operator mistakes healthy for caught up] -> Public guidance explicitly distinguishes stream health from the separate causal barrier.
- [Cross-change edits overlap] -> This change adds health inspection only; `add-causal-invalidation-barrier` adds progress/waiting. Neither overwrites the other's additive requirements.

## Migration Plan

The interface is additive. Update examples and public guides after the runtime surface exists; continue accepting advanced cache-core metrics calls. Reverting the feature restores the previous inspection route without data migration. Keep the Unreleased entry to one description of final behavior.
