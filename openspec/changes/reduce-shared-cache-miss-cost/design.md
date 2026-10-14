# Design

## Decisions

See the proposal for motivation and the delta spec for invariants. Enable the candidate only through new registrations; frozen version 5 and 6 configurations retain owner-selected misses.

The shared mapping gains one mutation serial per namespace and one fence serial per database. Every canonical write notifies the publisher, including writes without an existing identity state. Namespace resets retain their epoch fence. Database availability transitions and progress publication after an expiry increment the database fence. All serials are monotonic and stored atomically.

After a failed local lookup, the native reader captures these serials and a monotonic timestamp under the existing incarnation, availability, progress and epoch checks. It reads MongoDB and sends the encoded value with its namespace, keys, epoch, incarnation and token in one bounded one-way frame. Under the progress-publication lock, the owner checks authorization and freshness, begins a core identity capture, validates the token, then admits through the existing core. Token validation is the admission linearization point. Beginning the core capture first closes the gap between external serial checking and core generation checking. A write before the core capture changes the serial; a later write invalidates the core capture. Holding the progress lock through publication prevents expiry/recovery publication in this interval, without reversing the core-to-publisher lock order. Clock expiry after validation fences every local read until progress resumes, as for existing entries. No owner handle exists during the native read.

| Path          | Worker work                                                     | Owner work                                       |
| ------------- | --------------------------------------------------------------- | ------------------------------------------------ |
| Hit           | Existing atomic lookup, copy and decode                         | Existing batched recency drain                   |
| Captured miss | Constant-size token, one MongoDB round trip, one admission send | Decode one frame and run authoritative admission |
| Fallback      | Existing select RPC and native read                             | Existing handle and admission path               |

The admission transaction also holds the core availability lock, preventing a database transition between native-token validation and core insertion. Both locks precede namespace and publisher locks; publisher callbacks never acquire the progress lock.

Storage adds one word per namespace and database, plus one header word, independent of outstanding misses. Payload encoding/copy costs remain proportional to document bytes. The new path removes a blocking owner request and its reply; core admission and publication remain the expected CPU bottleneck.

Local miss capture requires an open data connection in the calling thread or event loop. A missing connection falls back to owner selection, preserving authentication and reconnection after transport loss. The existing local hit path remains independent of this connection. One-way sends enforce the registered frame limit after encoding; a combined key-and-value frame that exceeds it is dropped without closing the connection.

## Native admission queue

The [version 7 evidence](../../../reports/shared-worker-cache/v7/results.md) fails the eight-worker miss tail. With selection removed, a socket send remains on the worker's return path and the owner still processes each frame separately. Consolidating core locks would cross the explicit namespace/LRU lock-order boundary. Version 8 instead enables `native_admission_queue` with local capture, targeting the measured worker send and owner wakeup costs without changing core admission authority.

Each existing writable session ring gains a trailing byte queue, bounded by `queued_bytes_per_connection`. Disabled configurations retain the original mapping. Each record contains its byte length and already encoded frame in atomic words. Producer and consumer callers are serialized separately in the bindings. Release publication exposes only complete records; acquire consumption copies each record before releasing its space for reuse. Counter overflow and damaged indices fail closed. A killed producer cannot publish a partial record. Queue memory scales with worker sessions and is included in the group memory gate.

During each existing 50 ms sweep the owner drains at most `requests_per_connection` frames per peer, preserving time for other connections. Before parent control samples it drains each pending byte-bounded queue snapshot, including the last startup batch before residency checks. Queue frames must be one-way local admissions on the authenticated control session; malformed framing, operations or tokens detach only that peer. Lengths and positions are checked against the mapped capacity before allocation. The same protocol dispatch performs freshness checks and authoritative admission. Encoded bytes are copied before the worker returns, so later user mutation cannot change a queued value. Cancellation before read completion posts nothing.

Full, disabled or detached queues use the existing socket path. This also preserves reconnection and the frame-size guard. Queued messages count toward logical IPC bytes and one-way admissions, with a separate native-admission counter showing queue use. Sorted finds retain their existing transport. The new registration repeats calibration and every performance and timed fault phase; version 7 remains frozen.

## Risks

A namespace-wide serial rejects reads raced by unrelated writes. This is conservative and avoids an unbounded identity-generation table in shared memory; the active study measures the consequence. Publishing progress after an expiry must fence old tokens even when no owner RPC observed the stale interval. Counter wrap must fail closed. Malformed tokens must detach through the existing protocol error path. A native read that raises or is cancelled sends no admission and requires no owner cleanup.

## Delivery

The registration is committed before candidate timing. Measurements use clean source commits and disposable replica sets. Research results record the measured revisions and raw-output reproduction commands. No supported shared-cache mode is introduced, regardless of the outcome; issue #272's acceptance remains open until its registered measurements pass.
