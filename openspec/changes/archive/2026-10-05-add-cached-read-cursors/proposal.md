# Proposal

## Why

Cached `find()` and `aggregate()` currently return lists, requiring callers to change code that uses PyMongo cursors; asynchronous `find()` also requires an extra `await`. Returning compatible cursors will let the same read code consume native collections or cached views while retaining the explicit cached-read consistency contract.

## What Changes

- **BREAKING:** Return cursors from synchronous and asynchronous `find()` and `aggregate()`. Async `find()` returns its cursor immediately; async `aggregate()` remains awaited.
- Use one return contract. Eager consumers use `list(cursor)` or `cursor.to_list()` synchronously and `await cursor.to_list()` asynchronously; no return-mode setting or additional public type parameter is introduced.
- Preserve the corresponding PyMongo cursor interfaces, including iteration, partial `to_list()`, query chaining where supported, lifecycle operations, and native forwarding for requests that cannot be cached.
- Stream cache misses to callers and admit a result only after successful complete consumption, using bounded candidate storage and the existing invalidation guards.
- Return native cursors for tailable, exhaust, partial-result, and `$changeStream` requests, subject to PyMongo's own supported options.
- Distinguish batching options supplied before execution from later command-cursor batching. A local aggregation hit validates later `batch_size()` calls but never restarts native execution.
- Update public documentation, typed examples, affected tests, and benchmark callers; measure cached-cursor overhead against native reads using the same consumption pattern.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `cached-read-api`: Define cursor returns, execution and lifecycle behavior, complete-consumption admission, and native handling of cursor-only requests.

## Impact

The change affects both collection facades, shared bounded-capture helpers, public return annotations, documentation, examples, and benchmark code that assumes an eager `find()` call. Capture uses existing BSON primitives and the current cache admission path. No new runtime dependency or compatibility mode is planned.

This change covers the two multi-document read methods only. Cached views remain explicit read-only views; writes and administration stay on the original collection or `.raw`. Cache hits continue to skip native query execution and therefore cannot reproduce a fresh server/network error or a server-side query effect. The existing [adapter evaluation](../../../docs/development/research/read-through-collection-adapter-evaluation.md) documents that boundary. Count-option validation tracked in [#151](https://github.com/alessio-locatelli/client-query-cache/issues/151) is separate from this change.
