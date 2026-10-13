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

Admission batching was considered: it amortizes framing but cannot remove synchronous selection latency and adds flush/cancellation ownership. Consolidating core locks could reduce CPU for every manager but expands concurrency-sensitive production scope without eliminating the round trip. Neither is required for this candidate. Their comparative benefit remains unmeasured; task 3.1 determines whether the selected approach meets the issue's bound.

## Risks

A namespace-wide serial rejects reads raced by unrelated writes. This is conservative and avoids an unbounded identity-generation table in shared memory; the active study measures the consequence. Publishing progress after an expiry must fence old tokens even when no owner RPC observed the stale interval. Counter wrap must fail closed. Malformed tokens must detach through the existing protocol error path. A native read that raises or is cancelled sends no admission and requires no owner cleanup.

## Delivery

The registration is committed before candidate timing. Measurements use clean source commits and disposable replica sets. Research results record the measured revisions and raw-output reproduction commands. No supported shared-cache mode is introduced, regardless of the outcome; issue #272's acceptance remains open until its registered measurements pass.
