# Design

## Context

See [proposal.md](proposal.md) for motivation and the [delta](specs/change-stream-coherency/spec.md) for contracts. The two `streams.py` coordinators currently retain only successful supervisors. `StreamHealthRegistry` already retains failure observations without the coordinator lock. `DatabaseStreamSupervisor.start()` is single-use, so a failed supervisor cannot simply be restarted. A controlled local run with a mocked failing supervisor produced ten attempts and ten warnings for ten activations.

## Goals / Non-Goals

Preserve ownership by the coordinator and the existing supervisor reconnect loop. No permanent unsupported-server blacklist, background startup scheduler, new public status, or user-configurable startup policy is needed.

## Decisions

### Reserve locally, then perform I/O

Keep published supervisors and unpublished activation records keyed by database under the coordinator's short registry lock. An activation record retains its supervisor, ownership, completion signal, and startup retry state; publication discards that record. Healthy activation therefore keeps its existing single-lookup path. Claim the record and record a fixed `connecting` observation before releasing the lock for `start()`. After successful startup, first register the supervisor and finish updating its activation record, then install its live health callback as the final publication step before releasing the coordinator lock. Inspection therefore cannot see live supervisor health before registration is complete; competing activation calls cannot see the intermediate record while its lock is held. Failure retains the existing fixed failure observation; closure remains authoritative. Health inspection continues to use only the health registry's local lock, without waiting for activation I/O.

Other callers observing a pending record return `None`; the two managers must treat this return as `stream_unavailable` before checking cache availability. This avoids the brief interval when `start()` has marked a stream healthy but the attempt has not yet been published by its owner. Delegating health to the supervisor during this interval would expose `healthy` while the same activation still bypasses competing reads. The fixed observation and callback-last ordering keep the publication boundary consistent; task 1.2 verifies both publication intervals. No additional research is necessary.

Use `threading.Event` for synchronous completion and an asyncio completion primitive for asynchronous ownership; neither is waited on by ordinary competing reads. Completion and cleanup run on every exit path. No database-wide query lock is introduced.

Alternatives: retaining the global lock minimizes state but serializes network delays. Per-database locks with waiting callers isolate databases but still amplify latency for every read during an outage. Returning uncached reads while another caller activates is chosen because the existing API already permits stream-unavailable bypasses. The shutdown races require deterministic reproduction in task 1.3; no additional architecture research is necessary.

### Share retry arithmetic, not execution machinery

Add a small `_core/stream_activation.py` policy record using `RetryBackoff` and its existing caps. Its random sampler selects the upper half of each cap instead of the reconnect loop's full jitter interval: the strictly positive cooldown prevents a zero-delay initial retry. Store `time.monotonic()` deadlines, not sleeps. Failed attempts create a fresh single-use supervisor only after the next deadline; successful activation releases its failure history. Log once per actual failed attempt.

A fixed cooldown is simpler but keeps persistent failures at a fixed attempt rate. Background retries can recover idle databases but add workers and shutdown obligations without a waiting read to benefit. A permanent failure cache could hide corrected permissions or upgraded servers. The selected policy needs no research beyond deterministic clock/random tests in task 1.1. Established reconnects remain owned by their supervisor.

### Shutdown signals all owners before waiting

Split supervisor stop signaling from cleanup with a local, non-I/O stop request usable by both execution models. Closure first marks the registry closed and signals every successful or pending supervisor, making all their databases unavailable. It then releases the registry lock and waits for pending owners to finish native-resource cleanup, followed by established worker cleanup. A pending owner encountering shutdown must clean its late stream instead of publishing it. Set completion only after cleanup, including async cancellation; await cleanup before re-raising cancellation.

Cancellation and unexpected exceptions release the reservation without advancing startup backoff. While open, record unsuccessful startup locally; after closure, leave health terminal. `StreamStartupError` alone enters the cooldown path. Propagate unexpected exceptions and preserve existing lifecycle errors. Do not hold the registry lock while waiting for an owner or calling native close. Synchronous close callers join a shared completion event so manager cache release cannot overtake another caller's cleanup.

Having closure clean only published supervisors would lose resources created by an in-flight attempt. Cancelling a network call alone does not establish that a late native stream was released. Explicit ownership through completion is selected. The exact interleavings are covered by task 1.3; no separate research task is necessary.

### Async shutdown retains cleanup independently of its callers

On its first execution, async `close()` sets the coordinator's closed flag, closes the health registry, and signals every tracked supervisor before scheduling cleanup or suspending. It then creates and retains one shutdown task to own the waits and resource cleanup described above. Scheduling that task is not the closure boundary: an activation already in the ready queue must be rejected even if it runs before the cleanup task's body.

This transition runs without awaiting the asyncio registry lock. Once acquired, async registry critical sections contain no suspension, so another task cannot mutate activation records during the transition on the coordinator's event loop. Activation checks closure after acquiring the lock and again before publication; already-pending owners remain cleanup-owned. The synchronous coordinator retains its registry lock for the corresponding transition.

Every `close()` caller joins the retained task through `asyncio.shield`; if a caller is cancelled, it continues joining until cleanup finishes, then propagates cancellation. Repeated cancellation must not interrupt that join or cancel the retained task. Concurrent and subsequent callers join the same task even when the coordinator's closed flag is already set; that flag rejects activation, while task completion determines whether cleanup has finished. Retain existing visible cleanup-failure reporting.

The async manager releases its owned cache in a `finally` around the coordinator close call. Since cancellation is deferred until coordinator cleanup finishes, this preserves coordinator-before-cache release even when cancellation is re-raised.

Shielding an unretained coroutine can leave callers unable to join its cleanup. A retryable incomplete-shutdown state could deliver cancellation promptly, but would require another caller to finish releasing resources. Retained, joined cleanup avoids that obligation, at the cost of deferring cancellation while native cleanup blocks. Task 1.3 gates native cleanup and exercises cancelled, concurrent and repeated callers; no additional architecture research is necessary. This allocates one task at shutdown and adds no read-path work.

### Resource and measurement scope

Healthy activation and cooldown checks require one database-keyed lookup and short local locking, independent of other database count. State scales with encountered databases and is reclaimed on closure. Cooldown creates no timer, thread, task, or network call; permitted attempts keep the existing server check and watch operation. Native startup I/O still dominates the owning caller's latency. Task 1.4 measures that suspected bottleneck and checks the healthy path against the parent revision before claiming a benefit.

## Risks / Trade-offs

- Recovery after an idle failure waits for a later read. This follows the existing lazy activation model and must be clear in operations guidance.
- Competing first reads now bypass rather than wait for the owner. They retain native driver errors and consistency options.
- Owner cleanup can wait for driver I/O to finish. Client timeout settings remain the caller's responsibility; closure cannot claim to interrupt arbitrary native I/O immediately.
- Cancellation of async closure is delivered after cleanup; it cannot guarantee prompt cancellation while native cleanup remains blocked.
- Manager close and standalone coordinator close must both obey the same ownership protocol; cover both in task 1.3.
