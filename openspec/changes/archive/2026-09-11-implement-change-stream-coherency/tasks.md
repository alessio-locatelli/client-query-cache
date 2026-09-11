## 1. Route minimal change events

- [x] 1.1 Implement exactly one MongoDB 6.0+ database-scoped projected stream per active cached database with `show_expanded_events=True` and an event router for insert, update, replace, delete, drop, `dropDatabase`, rename, `create`, and invalidation; verify fixture tests retain every required routing and resume field, multiple cached databases each have a stream, and startup fails closed when expanded events are unavailable.
- [x] 1.2 Connect router outcomes to cache-core aliases, identity generations, and namespace generations (and namespace epochs plus physical reclamation for drop/rename/`dropDatabase`/`create`); verify external writes invalidate document and namespace-guarded entries, that clears invalidate identity-guarded entries too, that a `create` event advances epoch/generation for a namespace that previously did not exist, and that `create` physically reclaims any entries cached against that namespace while it was absent.

## 2. Implement synchronous recovery

- [x] 2.1 Implement synchronous start, stop, health transitions, and capped retry with jitter; verify startup failure, recovery, and close tests bypass cache use while unhealthy.
- [x] 2.2 Persist and resume with the identical stream configuration, including `show_expanded_events=True`; verify an unresumable cursor clears affected cache state before reopening and an invalidate event reopens from a safe post-invalidation position.

## 3. Implement asyncio recovery

- [x] 3.1 Implement an event-loop-bound asyncio stream task with equivalent lifecycle and recovery semantics; verify cancellation does not leak tasks or connections.

## 4. Verify coherency end to end

- [x] 4.1 Use independent raw writers to test update, delete, drop, `dropDatabase`, rename, resumable interruption, and lost-resume-history behavior in sync and asyncio suites; distinguish post-event invalidation from a cache hit concurrent with event delivery.

## 5. Close full-branch coherency findings

- [x] 5.1 Bind identity and namespace admission captures to a healthy database-availability generation, rejecting a capture created while unavailable or invalidated by a recovery transition; add focused cache-core regressions.
- [x] 5.2 Maintain a database-to-namespace reverse index and use it for database-wide invalidation; add a regression proving unrelated namespace metadata is not consulted.
- [x] 5.3 Serialize synchronous health and cache-availability transitions so a stop racing a successful reopen cannot restore cache eligibility; add a deterministic race regression.
- [x] 5.4 Disable cache availability before synchronous and asyncio shutdown cleanup begins; add blocked-cleanup regressions for both execution models.
- [x] 5.5 Run the prescribed quality checks and a whole-branch review; resolve all valid findings before completing the change.
- [x] 5.6 Publish async cache unavailability before an unhealthy health state; add a shared-cache ordering regression.
- [x] 5.7 Continue synchronous shutdown after a cursor-close error so the worker is joined and cache unavailability is retained; add a deterministic regression.
- [x] 5.8 Continue asyncio shutdown after a cursor-close error so coordinator shutdown is not interrupted; add a deterministic regression.
