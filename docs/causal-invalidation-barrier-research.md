# Deferred causal invalidation barrier: research reference

Status: **research retained; public feature deferred.** See the
[decision](decisions/defer-causal-invalidation-barrier.md) for rationale and reconsideration criteria.
The mechanism and API described here belong to an unmerged implementation, not the supported public interface.

## Provenance and evidence limits

The investigation and implementation are in
[PR #124](https://github.com/alessio-locatelli/client-query-cache/pull/124), branch
`add-causal-invalidation-barrier`. The immutable PR snapshot is
[`84592770436027c2da1d87c51944ffbc886e13ac`](https://github.com/alessio-locatelli/client-query-cache/tree/84592770436027c2da1d87c51944ffbc886e13ac).
Its [original report](https://github.com/alessio-locatelli/client-query-cache/blob/84592770436027c2da1d87c51944ffbc886e13ac/docs/causal-invalidation-barrier-proof.md)
and [implementation commit](https://github.com/alessio-locatelli/client-query-cache/commit/e4bea828ab7cd59513cf91f7cdf545eb9c8fab5e)
contain the full observations and benchmark summaries.

This reference checks the cited public contracts and curates those recorded results. It does not rerun the
experiments or certify the original report's claim of a complete proof. Raw outputs and full experiment scripts
were untracked; the original report preserves only partial reproduction sources. Retained measurements are
reported historical observations, not current performance guarantees.

Reported environment: MongoDB 8.0.4 and 8.3.11, PyMongo 4.18.1, Python 3.14.6; a one-member replica set and a
sharded deployment with two one-member shard replica sets, a one-member config server replica set, and `mongos`.
Both sync and asyncio were exercised. These topologies do not establish behavior under multi-member replication
lag or failover. Default-server latency experiments used `periodicNoopIntervalSecs=10` and
`max_await_time_ms=1000`.

## Documented contracts

- [PyMongo session state](https://pymongo.readthedocs.io/en/4.18.1/api/pymongo/client_session.html)
  exposes `operation_time` for the session's last operation. It does not identify which database was written or
  certify that the operation was a write. Sessions cannot run concurrent operations.
- [MongoDB's watch reference](https://www.mongodb.com/docs/v8.0/reference/method/Mongo.watch/)
  documents comparison and sorting of hex resume tokens and delivery of majority-persisted changes. Token
  comparability is documented; interpreting a comparison as the complete barrier proof is a further argument.
- The [driver change-stream specification](https://github.com/mongodb/specifications/blob/529a2dd14a4fc0e94bb9adca686bbcbdfd15f713/source/change-streams/change-streams.md#why-do-we-need-to-expose-the-postbatchresumetoken)
  defines `postBatchResumeToken` as progress through scanned oplog entries, including nonmatching changes.
  Drivers cache it after an empty batch or consumption of the final document in a batch.
- [PyMongo's change-stream API](https://pymongo.readthedocs.io/en/4.18.1/api/pymongo/change_stream.html)
  permits `try_next()` to return no event while updating `resume_token`. It issues one `getMore` when no document
  is buffered. `next()` waits for an event and does not return empty batches to the caller.
- [MongoDB's server parameters](https://www.mongodb.com/docs/v8.0/reference/parameters/#mongodb-parameter-param.periodicNoopIntervalSecs)
  document a default periodic no-op interval of 10 seconds. This setting alone is not a barrier latency bound.

## Investigated mechanism

The proposed API captured `session.operation_time` immediately after a write or committed transaction and
passed that boundary to a wait for one database in one manager.

1. For boundary `T`, open a temporary database change stream at the next BSON timestamp after `T`, with
   `batch_size=0`. Retain the server-issued token and close the stream. The experiments reported immediate
   availability of a high-water-mark target token on the tested topologies.
2. Advance the permanent invalidation stream with `try_next()`. Apply each returned event's invalidations before
   publishing its updated resume token as progress. Empty batches can also publish progress.
3. Complete the wait when the applied progress token's `_data` string sorts at or beyond the target.

The intended argument is that a stream starting after `T` cannot return events at or before `T`, and progress
past its target follows every event belonging to the boundary. This depends on ordering between the temporary
stream's target and the permanent stream's tokens, including their different pipelines, filtered events,
sharded merging, reconnects, and token format/version changes. Validate that argument before reusing it as a
public guarantee; successful probes are supporting evidence rather than a substitute for the contract.

## Useful counterexamples and invariants

| Candidate shortcut or race                           | Finding to preserve                                                                                                                            |
| ---------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| Complete after the first event at `T`                | The report observed four non-transactional inserts sharing one `clusterTime`. One event does not prove the whole group was invalidated.        |
| Wait only for a later matching event                 | A no-op write or filtered event may produce no event for the consumer. Empty-batch progress matters on quiet databases.                        |
| Use wire `getMore.operationTime` as applied progress | The report observed this time advancing while the sharded stream's token did not. A command reply's time is not proof of routed invalidations. |
| Publish progress before invalidating                 | A waiter can return while affected cached entries remain usable. Publication must follow application of invalidations.                         |
| Admit an old read after invalidation                 | A read starting before invalidation may finish afterwards. Existing generation/availability checks must prevent stale cache admission.         |
| Treat clearing after history loss as catch-up        | Clearing protects future cache use but does not prove missing events were processed. Loss of the required proof must fail a wait explicitly.   |
| Infer a write boundary from stream health            | A healthy stream can still be behind the write. Health and causal progress are different properties.                                           |

The original implementation also bounded activation, target acquisition, waiting, and cleanup with one
deadline, removed cancelled waiters, and kept cancellation of one waiter independent of the shared stream.
These are necessary lifecycle properties if a future proposal introduces waits.

## Reported latency and resource cost

| Workload                                    | MongoDB 8.0.4 | MongoDB 8.3.11 |
| ------------------------------------------- | ------------- | -------------- |
| Single write, idle replica set, sync        | 20.02 s       | 20.02 s        |
| Single write, idle sharded deployment, sync | 19.01 s       | 18.02 s        |
| No-op update, idle replica set, sync        | 10.01 s       | 10.01 s        |
| No-op update, idle sharded deployment, sync | 10.01 s       | 10.01 s        |

The original implementation commit separately reported about 1 second per wait when another database received
a write every 50 ms, and idle samples of 0.01, 19, and 20 seconds. Workload activity and timing matter; these
figures do not establish either a minimum delay or an upper bound under arbitrary server conditions.

The report attributed quiet completion to later periodic no-op oplog entries. Its approximate twice-interval
explanation is an interpretation of the experiment, not a documented service-level guarantee. Reducing
`max_await_time_ms` does not by itself create later oplog progress.

Each wait reportedly issued an `aggregate` and `killCursors` for its temporary stream, with no temporary-stream
`getMore`. On the sharded deployment this involved shard cursors. Permanent-stream idle traffic was unchanged
in the measured comparison. A future proposal must measure pool contention and acquisition cost at its expected
wait rate; one inexpensive wait does not establish scalability for a request-per-write workload.

## Boundary restrictions and API risks

The implementation supported majority-acknowledged writes and replica-set transaction commits; it excluded
sharded transaction boundaries. The report observed cross-shard transaction event times exceeding the session
operation time in 4 of 30 runs on 8.0.4 and 7 of 30 on 8.3.11:

```text
session.operation_time: Timestamp(1790874337, 123)
event increments:      123, 124, 124, 124, 124
```

A target at the next increment could precede events at that increment, so passing the operation-time boundary
does not prove that the entire transaction was invalidated. A higher observed cluster time is not automatically
a replacement causal contract. This is evidence against the proposed boundary assumption, not a diagnosis of
an upstream MongoDB defect.

The proposed boundary contained an operation time and manager identity, but no database identity. Calling
`wait_for_invalidations("analytics", boundary)` after writing to `shop` could wait on the wrong cache. Capture
also could not establish that the session's latest operation was the intended write, recover its write concern,
or detect that it represented a committed sharded transaction. Documentation-only preconditions leave ordinary
application mistakes possible; any future API must address these risks explicitly.

A `w: 1` write can be acknowledged and later rolled back without producing an invalidation event. However,
unspecified write concern is not automatically `w: 1`: MongoDB documents majority as the
[implicit default for most deployments](https://www.mongodb.com/docs/v8.0/reference/write-concern/#implicit-default-write-concern),
with exceptions and configurable defaults. The problem is verification of the effective concern for the
particular write, not that ordinary client construction necessarily violates it.

The delivered requests-cache, Celery, and py-abac examples poll consumer results after writes. Their integration
paths do not supply the session boundary needed by this API. Retaining that polling does not demonstrate that
the proposed barrier solves the examples' application needs. See the [examples](https://github.com/alessio-locatelli/client-query-cache/blob/main/examples/README.md).

## Independent timeout-context finding

The original report observed an asyncio worker started inside `pymongo.timeout()` inheriting the deadline and
later failing with `NetworkTimeout`. Starting it in a fresh `contextvars.Context()` avoided that outcome.
[Python documents](https://docs.python.org/3.14/library/asyncio-task.html#asyncio.Task) that tasks copy the current
context unless another is supplied. The maintained supervisor starts its worker with
`asyncio.ensure_future(self._run())` in [the caller's context](https://github.com/alessio-locatelli/client-query-cache/blob/main/src/client_query_cache/asynchronous/streams.py).
This source pattern is still present in the documentation change's `main` baseline, `fcdad08`.

This finding concerns ordinary stream ownership and is independent of the deferred barrier. It remains
unresolved by this documentation-only change and is not assigned the feature's low priority. An independent
fix should reproduce first activation under a short caller deadline, then verify that the shared stream remains
usable after that deadline expires, with an otherwise healthy disposable MongoDB deployment. The rejected
implementation and its
[asyncio regression tests](https://github.com/alessio-locatelli/client-query-cache/blob/84592770436027c2da1d87c51944ffbc886e13ac/tests/asynchronous/test_barrier_integration.py)
provide a starting point; isolate the worker-context fix rather than bringing in the barrier.

## Reproduction guidance

Inspect the pinned snapshot in a separate checkout, following the repository's contribution guidance for its
development environment:

```console
git fetch origin refs/pull/124/head
git worktree add --detach /tmp/cqc-barrier-reproduction 84592770436027c2da1d87c51944ffbc886e13ac
cd /tmp/cqc-barrier-reproduction
just pytest tests/synchronous/test_barrier_integration.py tests/asynchronous/test_barrier_integration.py
```

These historical tests check the implemented contract, not the default-server latency table. Their disposable
fixtures set `periodicNoopIntervalSecs=1`. History-loss tests use fault injection; the original research did not
establish a real-server history-loss reproduction. Use the pinned
[report](https://github.com/alessio-locatelli/client-query-cache/blob/84592770436027c2da1d87c51944ffbc886e13ac/docs/causal-invalidation-barrier-proof.md#reproduction)
for the target-token probe and topology outline. Reconstruct the missing measurement harness before claiming
an exact benchmark reproduction.

To reassess product suitability, measure both versions/topologies of interest with server defaults on disposable
deployments: a single write followed by no activity, a no-op write, and continuous activity in another database.
Record write/commit concern, topology, periodic no-op interval, await time, command counts, event timestamps,
target/progress tokens, and elapsed time. Recheck same-timestamp groups, filtered events, transactions,
reconnect/history loss, and stale admissions. Keep raw results untracked and retain a concise summary with the
commands used. Do not infer a future latency guarantee from the historical measurements here.
