# Design

## Context

See [proposal.md](proposal.md) for motivation and [specs](specs/shared-worker-cache/spec.md) for requirements.

A worker keeps a `LocalObservation`: hit and miss integers and a raw `dict[str, int]` of bypass reasons. Reasons are plain strings spelled two ways (`unportable-key`, `owner-unavailable`, `stream-starting` against `namespace_capacity`, `session`), and the owner's gate sends its own hyphenated strings over the wire. `snapshot()` sums the dict, which includes `oversized`; the process-local snapshot keeps oversized separate. The dict is mutated without a lock, so summing it can race a first-seen reason.

The owner already answers an `observe` request with `SharedCacheOwner.observation()`, a raw dictionary used by tests and benchmarks. It holds cache usage, per-database availability and progress, connection and capture counts, upstream command counts, owner counters and index publication. It lacks uptime, limits, tracked-namespace count and stream activation state. Owner and worker clocks are not compared; the owner computes everything it reports.

The library has no adopters yet, so each field must answer a question an operator can act on by changing configuration, deployment or the application. Anything else is rejected below instead of shipped speculatively.

## Goals / Non-Goals

**Goals:** a worker-local diagnostic that costs nothing on the hit path; an owner diagnostic collected only on request; reasons and owner statuses an operator can correlate; one definition per concept shared by owner, worker, tests and docs.

**Non-Goals:** cross-worker aggregation, owner-wide hit rates, history or rates, owner-scope OpenTelemetry (#424), a parent-side accessor on `SharedCacheServer`, and any freshness claim.

## Decisions

### D1. Two scopes, two accessors

`snapshot()` stays the local, I/O-free worker accessor. A new `owner_snapshot()` is the only owner accessor: a normal call on the synchronous manager, a coroutine on the asyncio manager, built on the endpoint's existing `request` so the 0.25 s request deadline bounds it. A synchronous caller blocks its thread for at most that deadline plus a reconnect attempt; an asyncio caller blocks nothing.

Alternatives:

- A combined `diagnostics()` call: one name to learn, but a free local read would cost an owner request and an owner outage would blur worker data. Rejected.
- Also `SharedCacheServer.owner_snapshot()` on the parent: lets a supervisor monitor without a worker, and could report owner process liveness. Declined by the maintainer: parents rarely run telemetry or an event loop, and workers already hold the credential. Unknown: whether a supervisor-side consumer exists; none is known, so nothing is tracked.

### D2. `None` means no answer; a snapshot means an owner answered

`owner_snapshot()` returns `None` when the endpoint yields no reply (timeout, refused connection, lost connection, cooldown after a failure). Returned snapshots carry `incarnation` (an opaque `int`, compared for equality) and `uptime_seconds` computed by the owner. A restarted owner reports a new incarnation and a small uptime with empty usage and zero counters, so consumers detect counter resets without keeping a baseline. The first call after an owner restart can return `None` because the stale connection fails before reconnecting; callers treat `None` as "this attempt got no answer". A closed manager raises `CacheClosedError`, because `None` would misreport it as an owner outage.

Alternatives:

- A status object with an `available` flag: self-describing in logs, but every consumer must check the flag before reading optional fields, which weakens typing. Rejected.
- Raising an error: impossible to ignore, but a health endpoint then needs `try`/`except` around a read-only probe, and the exception types would need a public hierarchy. Rejected.
- Tracking replacement inside the manager (a `replaced` flag): needs per-manager baseline state and answers a question `incarnation` already answers. Rejected.

### D3. Worker reasons: a dedicated enum, one spelling, normalized at the source

Add `SharedBypassReason` (a `StrEnum`) and `SharedBypassReasonCount`, ordered like `BypassReasonCount`. Its members are the ordinary reasons a shared manager can record: the `BypassReason` members that shared reads reach, plus `unportable_key`, `shared_scope`, `metadata_refresh`, `owner_unavailable`, `database_not_authorized`, `stream_starting` and `progress_expired`. Spellings use underscores everywhere. Module constants in the adapter and the owner's gate strings take their values from the enum, so the raw dict key, wire reason and public value are the same string and the snapshot maps keys with a dict lookup, falling back to `unspecified` on `KeyError`. The hit path and `record_bypass` are unchanged.

`bypasses` excludes oversized results and a new `oversized_bypasses` field reports them, matching `CacheSnapshot`. This corrects an undocumented divergence and lets the OpenTelemetry bridge treat both manager kinds identically. The snapshot copies the raw dict with `dict.copy()` before summing, which does not iterate Python-level state and so cannot raise during a concurrent insert.

Alternatives:

- Extend `BypassReason`: no second enum, but process-local snapshots and their `by_reason` metric would gain seven permanently zero series, changing existing output for users who cannot hit them. Rejected.
- Build the enum dynamically from `BypassReason`: no duplicated names, but type checkers cannot see dynamic members. Rejected; a test asserts every shared-reachable `BypassReason` value is present.
- Translate reasons when recording: removes spelling drift risk but adds a lookup to every bypass. Unnecessary once spellings agree.

### D4. Owner snapshot content is limited to actionable fields

| Field                                 | Operator question and action                                                                                                |
| ------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `cache_bytes`, `evictions`            | Is the budget too small? Raise `budget_bytes`.                                                                              |
| `index_entries`                       | Is the index full although bytes are free? Raise `slots`.                                                                   |
| `namespaces`                          | Are collections bypassing for capacity? Raise `namespaces` or reduce collection churn.                                      |
| `connections`, `rejected_connections` | Do `owner_unavailable` bypasses come from an exhausted limit rather than an outage? Raise `connections`.                    |
| `streams`                             | Why do reads count `stream_starting`, `stream_unavailable` or `progress_expired`? Check owner logs, MongoDB access or load. |
| `incarnation`, `uptime_seconds`       | Did the owner restart, so zeros mean a fresh cache?                                                                         |

`SharedCapacityUsage(in_use, limit)` is a frozen record used for the four capacities. `streams` is a tuple of `SharedDatabaseHealth(database_name, status)` in configuration order; `SharedStreamStatus` has the six values in the specs. A single owner helper derives the status from activation state, availability and progress freshness in the same order as the request gate, and a parametrized test pins each status to the reason the gate returns, so the two cannot drift. Derivation does not start activation.

The owner's `observation()` gains `uptime_seconds`, `limits`, tracked-namespace count and per-database `status`. Everything else it already returns stays for benchmarks and tests; no new request type is added. Tracked namespaces are counted per configured database on demand, O(namespaces), which is acceptable for an explicit diagnostic.

Rejected as not actionable or misleading:

- Owner `hits`, `misses` and `bypasses`: local-index hits never reach the owner, so they are not totals.
- Capture counts and `capture_limit_misses`: the limit is fixed at 4096 and not configurable.
- `rejected_admissions`, `expired_captures`, `lease_expiries`, IPC byte counts, peak counters and upstream command counts: no stable operator action maps to them; add later if a concrete case appears.
- Arena usage: the native layer does not report it, and publication failure from a full arena is not separable from other rejections. Unknown: whether the arena needs its own gauge; revisit only on a reported case.
- Time since a status began: needs a semantic definition across restarts of the stream and invites a freshness reading.

### D5. OpenTelemetry carries worker scope only

`register_cache_metrics` accepts either shared manager. For these it registers hits, misses, ordinary bypasses, oversized bypasses and `by_reason`, reusing the existing callbacks, whose snapshot field names the shared snapshot shares. It skips the evictions counter, the entry and resident-byte gauges and all stream instruments, and never contacts the owner. Existing instrument identities and process-local output are unchanged. Owner-scope metrics need periodic requests from every worker and a thread-safe path for asyncio endpoints; see #424.

Alternative: register owner gauges whose callbacks call `owner_snapshot()`. This duplicates identical series per worker and violates the no-polling requirement. Rejected for this change.

### D6. Example, tests and documents

The shared FastAPI example, an existing CI-verified integration with real workers, gains a `/diagnostics` route that returns the manager's `snapshot()` reasons and `await owner_snapshot()`; its self-check asserts a healthy stream, capacity within limits and consistent incarnations. Owner interruption and restart are demonstrated by focused tests with a real `SharedCacheServer` (`restart()` and `close()`), because the example's parent process cannot be driven over HTTP. The monitoring guide interprets each symptom from a table keyed by reason and status, and its examples are executed by those tests.

### D7. Cost

Hits and misses add no work. Bypass recording is unchanged. `snapshot()` is O(reasons) with a fixed vocabulary. `owner_snapshot()` costs one request, an owner-side O(databases + namespaces) walk and a reply of about 1 KiB, far below the frame limit. The change touches no hit-path code, so verification is inspection plus a before/after run of one shared hit/miss measurement on `main`.

## Risks / Trade-offs

- [Reason spelling change breaks tests or hidden consumers of the raw strings] → The strings are private; update the tests that pin them.
- [Aligning `bypasses` changes a shipped number] → Document it in the changelog; the previous value mixed two meanings.
- [A reply larger than the frame limit would look like an outage] → `max_entry_bytes` plus 65,536 bytes dwarfs the reply; a test with the smallest valid configuration pins this.
- [`healthy` is read as "caught up"] → The monitoring guide states the limit once and the shared guides link to it.
- [Owner `observe` calls inflate its `requests` counter] → Accepted; the counter is not exposed publicly.

## Migration Plan

Additive except the `bypasses` alignment. Reverting restores the three-field snapshot without data migration.
