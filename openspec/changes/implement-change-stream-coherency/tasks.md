## 1. Route minimal change events

- [ ] 1.1 Implement exactly one MongoDB 6.0+ database-scoped projected stream per active cached database with `show_expanded_events=True` and an event router for insert, update, replace, delete, drop, `dropDatabase`, rename, and invalidation; verify fixture tests retain every required routing and resume field, multiple cached databases each have a stream, and startup fails closed when expanded events are unavailable.
- [ ] 1.2 Connect router outcomes to cache-core aliases and namespace generations; verify external writes invalidate document and derived-result entries.

## 2. Implement synchronous recovery

- [ ] 2.1 Implement synchronous start, stop, health transitions, and capped retry with jitter; verify startup failure, recovery, and close tests bypass cache use while unhealthy.
- [ ] 2.2 Persist and resume with the identical stream configuration, including `show_expanded_events=True`; verify an unresumable cursor clears affected cache state before reopening and an invalidate event reopens from a safe post-invalidation position.

## 3. Implement asyncio recovery

- [ ] 3.1 Implement an event-loop-bound asyncio stream task with equivalent lifecycle and recovery semantics; verify cancellation does not leak tasks or connections.

## 4. Verify coherency end to end

- [ ] 4.1 Use independent raw writers to test update, delete, drop, `dropDatabase`, rename, resumable interruption, and lost-resume-history behavior in sync and asyncio suites; distinguish post-event invalidation from a cache hit concurrent with event delivery.
