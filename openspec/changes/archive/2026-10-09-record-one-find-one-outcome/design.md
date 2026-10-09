# Design

## Context

When a namespace has no unique-key metadata for its current index generation, `find_one()` performs the generic namespace lookup first and discovers unique keys only after that lookup misses. A generic hit therefore needs no `listIndexes` round trip. When discovery then matches a unique key, the unique-key path performs its own lookup. `CacheCore` records a miss inside every lookup that finds no valid entry, so the request records two misses.

Metadata stays unknown across reads when the index probe fails, because a failed probe is not stored and the next read probes again. A generic entry admitted by such a read is still hit by later reads before they probe.

## Goals / Non-Goals

**Goals:**

- One outcome per eligible `find_one()` (see the delta spec), at no extra cost on the generic hit path.

**Non-Goals:**

- Changing how many stream-unavailable bypasses one request can record; the monitoring guide already states that a request can record more than one bypass.
- Caching failed index probes or changing when metadata is discovered.

## Decisions

### Defer the generic miss while unique-key metadata is unknown

The cold-branch generic lookup passes a keyword-only `defer_miss` flag to `CacheCore.lookup_namespace()`, which then skips recording a miss and returns a `LookupResult` whose `deferred_miss` field is true. A hit and a stream-unavailable bypass are recorded as today. If discovery finds no unique key, the facade records the deferred miss through a new `CacheCore.record_miss()` before continuing on the generic path. If discovery finds a unique key, the deferred miss is dropped and the unique-key path records the request's only outcome. Warm reads, whose metadata is known, keep the current single lookup and are unaffected.

- Pros: exactly one hit or miss per request; the generic hit path keeps its order and issues no index probe; the bypass/miss distinction stays inside `CacheCore`, so the facade never infers it from a later, possibly different, availability check.
- Cons: `lookup_namespace()` gains a keyword and `LookupResult` a field; a request cancelled during discovery records no miss.
- Unknowns: none.

### Alternative: discover unique keys before the generic lookup

- Pros: no deferred state; one lookup per request.
- Cons: while probes keep failing, every read, including generic hits, would issue a failing `listIndexes` before its lookup, adding a round trip and a warning to reads that are hits today.
- Rejected; no further research is needed.

### Alternative: suppress the unique-key path's miss after a generic miss

- Pros: no `CacheCore` change.
- Cons: both unique-key lookups (alias-resolved identity and namespace-guarded) need the flag, and a unique-key hit after a recorded generic miss would still record a miss and a hit for one request.
- Rejected; no further research is needed.

### Alternative: document two misses

- Cons: leaves the counter skew that the issue reports and contradicts the existing one-outcome rule for find compatibility lookups in `cache-core`.
- Rejected.

## Risks / Trade-offs

- [The extra keyword and branch sit on the `find_one()` hot path] → Measure the generic hit and cold-miss paths before and after the change and record the numbers in the commit body.
- [A cancelled cold read records no miss] → Acceptable: the read never reaches MongoDB, and no other outcome is recorded either.
