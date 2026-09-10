## 1. Route minimal change events

- [x] 1.1 Implement exactly one MongoDB 6.0+ database-scoped projected stream per active cached database with `show_expanded_events=True` and an event router for insert, update, replace, delete, drop, `dropDatabase`, rename, `create`, and invalidation; verify fixture tests retain every required routing and resume field, multiple cached databases each have a stream, and startup fails closed when expanded events are unavailable.
- [x] 1.2 Connect router outcomes to cache-core aliases, identity generations, and namespace generations (and namespace epochs plus physical reclamation for drop/rename/`dropDatabase`/`create`); verify external writes invalidate document and namespace-guarded entries, that clears invalidate identity-guarded entries too, that a `create` event advances epoch/generation for a namespace that previously did not exist, and that `create` physically reclaims any entries cached against that namespace while it was absent.

## 2. Implement synchronous recovery

- [x] 2.1 Implement synchronous start, stop, health transitions, and capped retry with jitter; verify startup failure, recovery, and close tests bypass cache use while unhealthy.
- [x] 2.2 Persist and resume with the identical stream configuration, including `show_expanded_events=True`; verify an unresumable cursor clears affected cache state before reopening and an invalidate event reopens from a safe post-invalidation position.

## 3. Implement asyncio recovery

- [x] 3.1 Implement an event-loop-bound asyncio stream task with equivalent lifecycle and recovery semantics; verify cancellation does not leak tasks or connections.

## 4. Verify coherency end to end

- [ ] 4.1 Use independent raw writers to test update, delete, drop, `dropDatabase`, rename, resumable interruption, and lost-resume-history behavior in sync and asyncio suites; distinguish post-event invalidation from a cache hit concurrent with event delivery.
