# Design

## Context

See [proposal.md](proposal.md) for motivation and [the coherency delta](specs/change-stream-coherency/spec.md) for the required guarantee. Supervisors currently call blocking `next()`, save a resume token, and route projected events. They expose health but no applied causal frontier. The projected `clusterTime` is available; neither a healthy flag nor the saved token is an application-write boundary.

The [PyMongo session API](https://pymongo.readthedocs.io/en/stable/api/pymongo/client_session.html) exposes a session's last `operation_time`; it is not present on ordinary write-result objects. [MongoDB event documentation](https://www.mongodb.com/docs/v8.0/reference/change-events/update/) states that several events can share a `clusterTime`, including events outside a single transaction on MongoDB 8.0. [PyMongo change-stream documentation](https://pymongo.readthedocs.io/en/stable/api/pymongo/change_stream.html) states that `try_next()` can update a resume token even when returning no event. These facts rule out inferring a complete frontier from the first event at a timestamp or from a token's mere change.

## Goals / Non-Goals

**Goals:** A sound database-scoped success guarantee, explicit boundary provenance, finite resource lifetime, and no additional work on ordinary cached reads beyond unavoidable progress bookkeeping proven necessary.

**Non-Goals:** Global consistency across managers, transaction/session caching, cache population from writes, automatic marker writes, application-result polling, or decoding opaque resume tokens. Completion covers a supplied boundary, not future concurrent writes or synchronous authorization revocation.

## Decisions

### D1. Separate the proof phase from runtime work

This change has a blocking technical proof phase, followed by a runtime phase. The first phase is implementable research with fixed inputs and acceptance criteria; the public callable is not frozen by this draft. The later phase must not begin until this design names a concrete supported progress mechanism, a callable signature, boundary representation, exceptions, and topology support, backed by the required experiments and reviewed again. Passing file-existence status does not satisfy that gate.

Use only documented public PyMongo and MongoDB surfaces. Specifically test whether a session-associated write boundary can be related to a fully drained database stream using public operation/progress information. A strict later timestamp can establish progress for earlier events only if the supported topology's ordering proves it; it does not solve an idle/no-op boundary by itself. A changed or empty-batch resume token must not be ordered, parsed, or treated as a timestamp without an official supported contract.

Research output is `docs/causal-invalidation-barrier-proof.md`: cite supported MongoDB/PyMongo versions and authoritative ordering/progress sources; include reproduction commands, the success invariant, and adversarial traces. If public surfaces cannot prove quiet-stream completion, record the missing driver/server capability and stop the runtime phase. Do not substitute endless timeouts for a viable idle-stream guarantee. Do not expand to a marker collection or private driver hooks without a separate scope decision.

Alternative: ship a timestamp-based wait now and improve it later. Rejected because false success is worse than the current honest eventual-consistency boundary. Alternative: clear entries and claim the stream caught up. Rejected because local clearing is not proof of applied invalidations and majority visibility of the write still needs a causal argument.

### D2. Boundary provenance is explicit

The proof phase starts with acknowledged writes on the manager's own deployment through an explicit session, after transaction commit where applicable. Capture the immutable operation boundary only after the completed write/commit; do not pass a live session into the worker or use it concurrently. Establish and document the required write concern and causal relationship for each supported topology.

Reject unacknowledged writes, uncommitted transactions, foreign deployments, missing operation information, and unverifiable boundaries. A raw write result, the client's highest observed cluster time, elapsed wall time, and an upstream method's return value are not interchangeable causal proofs. For an upstream library that hides the session/boundary, document that consumer polling or a direct read remains necessary; do not claim the new operation can recognize that write automatically.

### D3. Publish only fully applied progress

The intended ordering is:

```text
completed acknowledged write --> immutable database boundary
stream receives batch --> apply every affected invalidation
proof establishes complete progress through boundary --> publish frontier
publish frontier --> wake eligible waiters --> successful return
```

A timestamp equal to the target is insufficient unless the mechanism proves the entire equivalence class has drained. Filtered events, transaction event groups, and shards must be included in that reasoning. An in-flight read captured before an applied invalidation must continue to fail existing generation/availability admission checks. No waiter is completed merely because the worker read a batch or saved a token before routing its events.

Progress carries a continuity generation. Resumable reconnects suspend completion while continuity is uncertain. History loss, namespace/database invalidation, or stream recreation invalidates the old proof; fail affected waiters explicitly rather than claiming cache clearing observed the requested write. A new barrier can establish a new valid boundary after recovery. Shutdown fails pending waiters and releases their resources.

### D4. Wait without polling consumers or retaining write history

Once the proof mechanism is selected, keep one frontier/continuity record per database and waiters only for active calls. Use a synchronous condition/event mechanism and asyncio futures/events with equivalent outcomes. Each call requires an explicit finite positive timeout; validate it before activation. Use a monotonic absolute deadline covering startup, progress acquisition, waiting, and recovery work. Cancellation removes only its waiter, not the shared stream.

No per-write event log or background task per completed write is retained. A barrier can activate the existing database supervisor but cannot create a second permanent watcher. If additional temporary public-driver operations are needed by the proven mechanism, their count, pool usage, and deadline/cleanup bounds must be stated before runtime work.

### D5. Fixed proof matrix and resource evidence

Run experiments against a disposable MongoDB 8.0+ replica set and a disposable sharded topology; the library advertises both. Cover two writes sharing a timestamp, a multi-document committed transaction, different collections, deletes, bulk/no-op writes, a quiet database, filtered-out events, readers racing invalidation, multiple simultaneous waiters, resumable reconnect, history loss, drop/recreate, shutdown, and cancellation. Use native sync and asyncio clients. If a topology cannot satisfy the invariant, narrowing support changes this proposal and needs an explicit scope decision before runtime work.

Expected retained progress storage is O(D), with O(W) memory for W outstanding waits, and no retained per-write history. Publishing progress can wake O(W) waiters; evaluate ordered boundary indexing if measured contention makes scanning material. The experiment must determine any extra round trips and whether moving from `next()` to `try_next()` changes polling/getMore costs. Record idle traffic, wait latency, CPU, allocations, and normal hit-path overhead against the current supervisor baseline. Raw evidence stays untracked; the proof report and implementation commit body contain concise measurements and commands.

## Risks / Trade-offs

- [No supported public progress mechanism meets quiet/sharded guarantees] -> Stop after documenting the blocker; leave runtime tasks open and the change active. The task list does not authorize weakening the invariant.
- [A same-timestamp event releases waiters too early] -> Require complete-frontier evidence and adversarial grouped-event traces before runtime implementation.
- [A deadline is bounded only after startup] -> Apply one absolute deadline to the entire barrier path and validate network timeout interactions.
- [A wait increases connection-pool pressure] -> Reuse supervision, measure any necessary temporary operations, and bound cleanup under cancellation and shutdown.
- [Diagnostics and barrier edits overlap] -> Health inspection remains independent; a healthy status does not expose or replace causal progress.

## Migration Plan

The proof phase introduces no runtime API. After its gate is satisfied, runtime additions are opt-in; existing read consistency and client ownership remain unchanged. Update consumer examples only where a real supported boundary can be obtained. Roll back runtime additions without persisted-data migration. A failed proof is a concrete blocker, not completion of the promised feature.
