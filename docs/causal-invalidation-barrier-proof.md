# Causal invalidation barrier proof

Status: **proof complete with a narrowed scope.** The mechanism below is sound for replica sets, including committed transactions, and for non-transactional writes on sharded clusters. On sharded clusters, `ClientSession.operation_time` captured after a committed cross-shard transaction is not a sound boundary, because change events of that transaction can carry a later `clusterTime`; this boundary is documented as unsupported. See [Decisions](#decisions).

## Pinned environment

| Component       | Version                                                                                                                |
| --------------- | ---------------------------------------------------------------------------------------------------------------------- |
| MongoDB server  | 8.0.4 (`docker.io/library/mongo:8.0.4-noble`, the supported floor) and 8.3.11 (`docker.io/library/mongo:8.3.11-noble`) |
| PyMongo         | 4.18.1 (`uv.lock`)                                                                                                     |
| Python          | 3.14.6                                                                                                                 |
| Replica set     | one data-bearing member, `rs0`                                                                                         |
| Sharded cluster | one-member config server replica set, two one-member shard replica sets (`s1`, `s2`), one `mongos`                     |

Both topologies run with server defaults, so `periodicNoopIntervalSecs` is 10. Every experiment ran on both server versions; results are identical unless a version is named.

## Authoritative sources

- MongoDB 8.0 `Mongo.watch()` reference: "With hex-encoded string resume tokens, you can compare and sort the resume tokens." ([source](https://www.mongodb.com/docs/v8.0/reference/method/Mongo.watch/))
- MongoDB 8.0 change streams: event tokens identify an event; high-water-mark tokens "represent a point in time without an associated change event", and the server periodically advances them; on idle shards the advance may be infrequent ([source](https://www.mongodb.com/docs/v8.0/changeStreams/)).
- MongoDB 8.0 server parameters: `periodicNoopIntervalSecs`, default 10, is "the duration in seconds between noop writes on each individual node" ([source](https://www.mongodb.com/docs/v8.0/reference/parameters/#mongodb-parameter-param.periodicNoopIntervalSecs)).
- Driver change stream specification: `postBatchResumeToken` "represents the oplog entry the change stream has scanned up to on the server (not necessarily a matching change)"; drivers cache it after an empty batch or after the last document of a batch ([source](https://github.com/mongodb/specifications/blob/529a2dd14a4fc0e94bb9adca686bbcbdfd15f713/source/change-streams/change-streams.md#why-do-we-need-to-expose-the-postbatchresumetoken)).
- PyMongo `ChangeStream` exposes only `alive`, `close()`, `next()`, `resume_token`, and `try_next()`; `try_next()` runs at most one `getMore` ([source](https://pymongo.readthedocs.io/en/4.18.1/api/pymongo/change_stream.html)). `next()` is a loop over `try_next()` that does not return to the caller on empty batches.
- PyMongo `ClientSession.operation_time` is the `operationTime` returned by the session's last operation ([source](https://pymongo.readthedocs.io/en/4.18.1/api/pymongo/client_session.html)).

## Terms

- **Operation time**: the BSON `Timestamp` a server returns for an operation; PyMongo exposes the last one per explicit session.
- **Cluster time**: the gossiped logical clock (`$clusterTime`); a session's or client's highest observed value is not tied to a specific write and is not used as a boundary.
- **Event `clusterTime`**: the oplog time of the entry a change event was produced from. Several events can share it.
- **Resume token**: opaque position in a change stream. This report never decodes, constructs, or parses a token. It only compares the `_data` hex strings of tokens issued by the server, which the `Mongo.watch()` reference documents as comparable and sortable.

## Boundary provenance

The boundary is the immutable `bson.Timestamp` copied from `session.operation_time` after the write or `commit_transaction()` returned. The worker only ever receives that value, never the session.

| Input                                                                                     | Observed (both topologies, sync and asyncio)                                                              | Verdict            |
| ----------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- | ------------------ |
| Acknowledged write in an explicit session                                                 | `operation_time` equals the event `clusterTime`                                                           | accepted           |
| Unacknowledged write (`w=0`) in an explicit session                                       | PyMongo raises `ConfigurationError: Explicit sessions are incompatible with unacknowledged write concern` | cannot be produced |
| Session with no completed operation                                                       | `operation_time is None`                                                                                  | rejected           |
| Session inside an open transaction                                                        | `in_transaction is True`                                                                                  | rejected           |
| Session of another `MongoClient`                                                          | `session.client is not manager.client`                                                                    | rejected           |
| Committed replica-set transaction across collections                                      | all events share one `clusterTime` equal to `operation_time`                                              | accepted           |
| Multi-document `update_many`/`delete_many`, replica set and sharded (52 runs per version) | no event `clusterTime` exceeded `operation_time`                                                          | accepted           |
| Committed cross-shard transaction                                                         | event `clusterTime` exceeded `operation_time` in 4 of 30 runs on 8.0.4 and 7 of 30 on 8.3.11              | **unsound**        |

Cross-shard transaction trace, MongoDB 8.0.4 sharded cluster, collection `a` hashed across `s1`/`s2`, collection `b` unsharded on `s2`, one transaction inserting four documents into `a` and one into `b`:

```text
events (coll, _id, clusterTime.inc): a 0-0 123, a 0-1 124, a 0-2 124, a 0-3 124, b 0 124
session.operation_time = Timestamp(1790874337, 123)
session.cluster_time   = Timestamp(1790874337, 124)
```

A barrier targeting the operation time would release after the event at increment 123 while four events of the committed transaction are still unapplied. The session's cluster time happened to cover every event in all 60 runs, but no MongoDB or PyMongo contract relates a gossiped cluster time to a committed transaction's change events, so it is not accepted as proof.

Write concern: the change stream only returns majority-committed history, so the barrier cannot complete before the oplog position after the boundary is majority-committed. A `w: 1` write rolled back after acknowledgement produces no event; the barrier then completes without an invalidation, which leaves the cache consistent with the surviving data but not with what the application believed it wrote. The supported boundary therefore requires `w: "majority"` writes and commits; the library cannot verify the write concern from a session, so this remains a documented precondition.

## Relating the boundary to applied stream progress

### Rejected mechanisms

| Mechanism                                                  | Counterexample                                                                                                                                                                                                                                                                                  |
| ---------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Release on the first event at the boundary's `clusterTime` | A non-transactional `insert_many` of four documents on the replica set produced four events sharing one `clusterTime`, none of them in a transaction.                                                                                                                                           |
| Release on any event with a strictly later `clusterTime`   | Sound, but a no-op boundary (`update_one` matching nothing) on an idle database produced zero events in every run, so the wait never ends without an unrelated later write.                                                                                                                     |
| Wire `getMore` `operationTime`                             | Not exposed by `ChangeStream`; reading it needs a command listener registered when the application constructs its client. On the MongoDB 8.0.4 sharded cluster it advanced across three empty `getMore` replies while the stream's resume token stayed unchanged, so it is not stream progress. |
| Decoding the high-water-mark token's timestamp             | Excluded by the design; MongoDB only provides an unsupported `mongodb-labs` snippet for it.                                                                                                                                                                                                     |

### Candidate mechanism: server-issued target token

1. Validate the boundary as above and capture `T = session.operation_time`.
2. Open a temporary database change stream with `start_at_operation_time=Timestamp(T.time, T.inc + 1)` and `batch_size=0`, read its `resume_token`, and close it. The server returns a high-water-mark token at the requested start immediately, on both topologies, before any `getMore`.
3. The permanent supervisor calls `try_next()` instead of `next()`. After every call it routes the returned event, if any, and only then publishes `stream.resume_token["_data"]` as the applied frontier. With `next()` the frontier never advances on an idle stream, because empty batches never return to the supervisor.
4. The barrier succeeds when `frontier >= target`.

Soundness argument: the target is a position in the database's change stream at which no event with `clusterTime <= T` can be returned, because the server would not return such an event to a stream started at `T + 1`. Tokens sort in stream order, so any frontier at or above the target lies after every event with `clusterTime <= T`. The supervisor publishes a token only after routing every event at or before it: inside a batch PyMongo's token is the returned event's `_id`, and after the last event of a batch it is the `postBatchResumeToken`, which also covers events removed by the server-side `$match`. On a sharded cluster `mongos` merges shard streams in token order and its high-water mark does not pass a shard that has not advanced, which matches the observed holdback of up to 10 seconds below.

Adversarial traces (each tuple: event at the boundary's `clusterTime`?, frontier at or above target after routing it):

```text
replica set, insert_many of 4, sync:      (at, False) (at, False) (at, False) (at, False)  -> completes on a later empty batch
replica set, insert_many of 4, asyncio:   (at, False) (at, False) (at, False) (at, False)  -> completes on a later empty batch
replica set, transaction over a and b:    (at, False) (at, False)                          -> completes on a later empty batch
sharded, insert_many of 4 (split by shard): (earlier, False) x3 (at, False)                -> completes on a later empty batch
sharded, 6 single writes across shards:   (earlier, False) x5 (at, False)                  -> completes on a later empty batch
```

No received event or saved token released a waiter before every event at the boundary had been routed.

### Quiet-stream completion and latency

The frontier crosses the target only after the oplog contains an entry later than `T`. On an idle deployment that entry is the server's periodic no-op write, so no marker write, token decoding, private driver hook, or later application write is needed. Measured with `max_await_time_ms=1000`, as MongoDB 8.0.4 / 8.3.11:

| Boundary                                             | Replica set       | Sharded           |
| ---------------------------------------------------- | ----------------- | ----------------- |
| Single write in a cached collection, sync            | 20.02 s / 20.02 s | 19.01 s / 18.02 s |
| Filtered `collMod` (no relevant event), sync         | 20.01 s / 20.01 s | 19.00 s / 20.01 s |
| No-op update on an idle database, sync               | 10.01 s / 10.01 s | 10.01 s / 10.01 s |
| No-op update, asyncio, two waiters (third cancelled) | 10.01 s / 10.01 s | 8.01 s / 9.01 s   |

The bound is roughly twice `periodicNoopIntervalSecs` plus `max_await_time_ms`, because a node skips its no-op when its last write is newer than the previous check. On a busy deployment, any later oplog entry, in any database, advances the frontier. MongoDB documents `appendOplogNote` as the way to advance idle shards faster; that is a server write, which the design excludes without a separate scope decision.

The cancelled asyncio waiter raised `CancelledError` while the remaining waiters and the stream completed normally.

### Resource cost

- Supervisor: `try_next()` issues one `getMore` per call, exactly as `next()` does internally, so idle traffic is unchanged: one empty `getMore` per `max_await_time_ms`, observed as 10 empty `getMore` commands per 10-second wait.
- Barrier: one `aggregate` and one `killCursors` on the temporary stream, observed with a command listener on both topologies, using one pooled connection for the duration of those two round trips. On a sharded cluster `mongos` opens and closes a cursor on every shard for that `aggregate`.
- Retained state: one frontier string per watched database and one waiter per outstanding call; no per-write history.

## Continuity and lifecycle

Measured with the prototype supervisor, which reopens with `resume_after` on a driver error and with `start_after` after an `invalidate` event, on MongoDB 8.3.11:

| Scenario                                           | Replica set                                                                                                                      | Sharded                                                          |
| -------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| `killAllSessions` while a barrier waits            | supervisor reopened once with `resume_after`; barrier completed in 18.02 s                                                       | reopened once; completed in 14.03 s                              |
| Restart of the only `mongod` while a barrier waits | PyMongo resumed inside `try_next()`; barrier completed 0.41 s after the restart command returned                                 | not run; restarting the single-container cluster re-initiates it |
| `dropDatabase`, recreate, write                    | one `invalidate`; the barrier pending from before the drop and a new barrier after the recreate both completed, 20.03 s in total | one `invalidate`; both completed, 19.84 s in total               |

Resume tokens issued before a reconnect or an `invalidate` keep comparing correctly with tokens issued after it, so continuity survives both. Losing resume history cannot be produced cheaply against a real server: the minimum oplog is 990 MB, and a stream started at `Timestamp(1, 1)` was accepted by both topologies rather than failing with `ChangeStreamHistoryLost` (code 286). History loss is therefore exercised by fault injection in the stream tests. When it happens, the supervisor restarts without a resume token; events between the last applied token and the new stream are never applied, so waiters pending at that moment fail, and later barriers whose target precedes the new stream's first token fail too. After the initial activation of a database, no such restriction exists: nothing for that database was ever cached, so no earlier invalidation is relevant.

Activation and acquisition deadline: `server_info()` against an unreachable address under `pymongo.timeout(0.5)` raised `ServerSelectionTimeoutError` after 0.50 s (sync) and 0.51 s (asyncio), although the client's `serverSelectionTimeoutMS` was 30000. A task created inside `pymongo.timeout(1.5)` with `asyncio.create_task()` inherits the deadline and its permanent change stream failed with `NetworkTimeout`; the same task created with a fresh `contextvars.Context()` kept polling. Threads do not inherit context in the standard 3.14.6 build (`sys.flags.thread_inherit_context == 0`). The asyncio supervisor must therefore start its task in a fresh context, or a caller's `pymongo.timeout()` ends the shared stream.

Ordinary cached reads do not touch any of this: the hit path is unchanged, and the only supervisor change is calling `try_next()` instead of `next()`. Normal-hit overhead, allocation, and many-waiter contention are measured against the runtime code in task 4.1.

## Implemented progress semantics

- Both supervisors iterate with `try_next()`. After each call they route the returned event, if any, then save the stream's resume token and publish its `_data` string as the database's frontier under the same lock or event-loop step that registers waiters. A stream that stops being `alive` without an event takes the existing reconnect path.
- Opening or reopening a stream publishes nothing: a token reported before the first iteration may precede events the stream has not routed yet. A stream that fails before its first iteration has no resume token, so the supervisor treats it as lost continuity, as it does for an unresumable reopen.
- A reopen with `resume_after` or `start_after` keeps the frontier and pending waiters. An unresumable reopen clears the database's namespaces, fails pending waiters with `BarrierContinuityError`, and makes the first token published by the next stream the floor below which later targets fail.
- `wait_for_boundary()` acquires the target from a temporary stream under `pymongo.timeout()`, registers one waiter, and removes it on every exit path. Stopping a supervisor fails pending and later waiters with `BarrierClosedError`.
- Supervisor threads and tasks run in a fresh `contextvars.Context`.

## Decisions

1. **Cross-shard transactions on sharded clusters are an unsupported boundary.** The guarantee covers replica sets, including committed transactions, and non-transactional writes on sharded clusters. The library cannot tell from public session state that the last operation committed a transaction, so this is a documented precondition. Applications that commit cross-shard transactions keep reading from the database or polling.
2. **Idle completion latency is accepted and documented.** Barriers only read; on an idle deployment completion waits for the server's periodic no-op write, up to about twice `periodicNoopIntervalSecs` plus `max_await_time_ms`. Any other write in the deployment ends the wait sooner.
3. **Token ordering.** The `Mongo.watch()` statement that hex resume tokens can be compared and sorted is read as stream order. This is the mechanism's residual dependency on server documentation.

## Reproduction

Start disposable deployments with Podman (from a Toolbx or Distrobox container, prefix with `just podman --`):

Replace `8.0.4-noble` with `8.3.11-noble` for the second version.

```console
podman run -d --rm --name cb-rs --network host docker.io/library/mongo:8.0.4-noble --replSet rs0 --port 27117 --bind_ip_all
podman exec cb-rs mongosh --quiet --port 27117 --eval 'rs.initiate({_id:"rs0",members:[{_id:0,host:"localhost:27117"}]})'
```

For the sharded cluster, run one `mongo` container of the same version with `--network host` and an entrypoint that starts `mongod --configsvr --replSet cfg --port 28019`, `mongod --shardsvr --replSet s1 --port 28018`, and `mongod --shardsvr --replSet s2 --port 28020`, initiates each as a one-member replica set, then starts `mongos --configdb cfg/localhost:28019 --port 28017` and calls `sh.addShard()` for both shards.

Target token and frontier comparison (sync; the asyncio form awaits `watch()`, `try_next()`, and `close()`):

```python
from bson import Timestamp


def target_token(database, boundary):
    after = Timestamp(boundary.time, boundary.inc + 1)
    temporary = database.watch(start_at_operation_time=after, batch_size=0)
    try:
        return temporary.resume_token["_data"]
    finally:
        temporary.close()


def step(stream, route, publish):
    event = stream.try_next()
    token = stream.resume_token["_data"]
    if event is not None:
        route(event)
    publish(token)
```

Cross-shard transaction probe, run against `mongos` with `db.a` sharded on `{_id: "hashed"}`:

```python
with client.start_session() as session:
    session.with_transaction(
        lambda s: (
            [db.a.insert_one({"_id": f"{attempt}-{i}"}, session=s) for i in range(4)]
            + [db.b.insert_one({"_id": str(attempt)}, session=s)]
        )
    )
    boundary = session.operation_time
# read the five insert events from a database change stream opened beforehand
# and compare max(event["clusterTime"]) with boundary
```
