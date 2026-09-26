## 1. Document the public interface

- [ ] 1.1 Use `writing_readme.md` as the checklist when replacing the proof-of-concept README: lead with the project's value and evidence, keep it concise and scannable, and move detailed reference and operations material into `docs/`; include verified audience, topology prerequisites, installation, sync/async quick starts, lifecycle, consistency, and non-goal guidance, and verify every sample against the public API.
- [ ] 1.2 Publish the API reference and prototype migration guide; verify it covers configuration, limits, ownership, raw fallback, and rollback to PyMongo collections. Ownership guidance SHALL explicitly state that a `CacheManager` instance and the `CacheCore`/`ChangeStreamCoordinator` it owns are exclusive to that instance: sharing one `CacheCore` across more than one `ChangeStreamCoordinator` (or activating the same database from two coordinators over one `CacheCore`) is unsupported, per `implement-change-stream-coherency`'s `design.md`, because per-database stream-health availability is a single flag with no per-owner isolation, so one supervisor stopping can silently mark another supervisor's still-healthy database unavailable.

## 2. Document architecture and operations

- [ ] 2.1 Add system requirements, capacity estimation, HLD/LLD, retry/error, observability, security, connection-pool, and recovery guidance; verify internal and external references resolve. Capacity estimation SHALL explicitly cover the process-local resource model decided in `implement-cache-core`'s `design.md`: each `CacheManager` instance opens one change-stream cursor per active cached database it watches (not one cursor total), a synchronous and an asyncio `CacheManager` for the same deployment in one process do not share a budget or any cursor, and each additional process caching the same deployment multiplies the same per-instance cursor and budget count again. Give concrete, high-level guidance (not internal mechanics) for deployments where this multiplication matters most, e.g. a high-fan-out or short-lived-process model such as one process invocation per request, or a manager caching many databases.
- [ ] 2.2 Add workload-selection and performance guidance linked to the retained reports from `benchmark-change-stream-costs`; verify it makes no universal or unsupported performance claim.

## 3. Verify public documentation

- [ ] 3.1 Run all documented commands and examples in a clean supported environment, correct any mismatch, and record the exact validation evidence.

## 4. Code Quality

- [ ] 4.1 Scan the entire file for edited or added tests (including pre-existing tests within the file) and ensure that the "Writing Tests" guidelines from `AGENTS.md` are applied, including test parametrization.
- [ ] 4.2 If you are Claude Code, confirm that you added no new prose to the code (all "why" explanations must go in the specs and commit bodies). OpenAI Codex is exempt from this rule because it understands the difference between garbage and valuable code comments.
