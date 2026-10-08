# Design

## Context

See [proposal.md](proposal.md) for motivation and the [delta](specs/usage-examples/spec.md) for acceptance criteria. At planning time, `add-fastapi-catalogue-example` has no implementation in this checkout. **Implementation is gated on that change being delivered and reviewed.** Its [design](../add-fastapi-catalogue-example/design.md) establishes the target script, trusted principals, lifespan, direct mutation workflow, and hosted guide. Task 1.1 reconciles this plan with the delivered artifacts before editing them; this change does not implement that prerequisite.

Current `tests/examples/test_examples.py` parametrizes subprocess execution, and `just typecheck-examples` discovers `examples/*.py`. The prerequisite will register the catalogue program there. No extra runner is needed. The async manager exposes synchronous, non-activating public inspection methods; direct collection calls do not record cache outcomes.

## Goals / Non-Goals

Use restart-based configuration changes so resource and rollback evidence are easy to attribute to one deployment mode. Live flag updates, percentage assignment, a feature-flag service, and production authentication implementation are outside this demonstration.

## Decisions

### Extend the existing application boundary

Add a startup boolean `content_cache_enabled`, defaulting to false, to the catalogue's application configuration/factory. The deployment supplies the boolean from its own configuration; the self-check passes explicit values. The repository selects its raw or cached content collection once during lifespan startup, after configuration is resolved. Request data never chooses the flag. Keep the prerequisite's injected identity and permission dependencies ahead of repository calls.

Retain its one client and manager per lifespan even when disabled. Manager construction and inspection do not activate a stream; raw-only operation should report `not_started`. This avoids optional resource ownership and allows comparable public observations. Once enabled, the manager is reused until shutdown. A package switch would simplify call sites but impose application rollout policy on the library; per-request managers would demonstrate unnecessary startup work. A second standalone program would isolate the scenario but duplicate the application and authentication demonstration. No research is needed for these alternatives; task 1.1 checks fit against the delivered factory.

### Choose an explicit direct-read policy

Use primary read preference and explicit majority read concern for content in both modes. This makes the direct policy visible and fits the prerequisite's majority write and session-based mutation-response workflow. Preserve that workflow without routing it through the selected content handle. Matching concerns does not make cached hits current or make mode availability identical: hits skip server query execution, while misses require server access and stream availability controls admission.

An unspecified direct concern permits deployment defaults but obscures the comparison. Explicit local concern could make a useful different availability example, but introduces a policy contrast unnecessary for this small scenario. No additional research is required; task 1.2 checks the chosen options and preserves the prerequisite's consistency controls.

### Exercise successive deployments over one dataset

Extend the existing executable self-check with three context-managed lifespans: disabled, enabled, disabled. Seed once and perform final cleanup after all phases, using the appropriate live client's application loop. Preserve the existing standalone run's disposable database warning; do not reset data at intermediate startup. Retain references to each manager for post-shutdown inspection. Application requests within a phase share resources; successive lifespans get new resources.

Reuse the existing tenant and HTTP assertion helpers across phase values. In the enabled phase, first execute a cold eligible read, repeat it for hit evidence, and make an explicit session-bound cached-view read for a deterministic `session` bypass. The session probe is a self-check observation rather than a change to the application's direct freshness workflow. Preserve the prerequisite's write and bounded eventual-invalidation checks, then verify its updated document through direct requests in the rollback phase. Failed HTTP, isolation, counter, or cleanup evidence exits with a named error.

Snapshots before and after controlled operations give exact deltas; never equate hits plus misses plus bypasses with HTTP request totals. Report `snapshot()` outcome counts, bypass reasons, resident bytes, entries and budget; use `stream_health_snapshot(database_name)` to show disabled operation and closure. Do not log connection strings or document contents as telemetry. Exact integration details remain contingent on the prerequisite's delivered self-check and are resolved by tasks 1.1 and 1.3.

Live toggling would reuse one lifespan but leave streams active after disabling unless separately shut down. Restart-based selection shows completed cleanup with fewer moving parts. Keeping independent scripts would require repeated seeding and provide weaker rollback evidence. Neither alternative needs a prototype; the existing lifespan test mechanism is sufficient.

### Keep guidance canonical

Extend `docs/user/examples/fastapi.md` with a short rollout section and link it from `docs/user/operations/deployment.md`. Reuse the script snippet already planned there. Link the current consistency, [monitoring and OTel](../../../docs/user/operations/monitoring.md), and [rollback](../../../docs/user/reference/api.md#rollback-to-plain-pymongo) guides instead of copying their contracts. A separate rollout guide adds navigation and duplicate context without enough new material to justify it. No documentation research is needed.

## Risks / Trade-offs

- The delivered catalogue may use a different factory or seeding boundary. Resolve those concrete differences in task 1.1; do not invent a second application or silently implement the prerequisite.
- Cache activation is lazy. Keep eligible reads sequential for cold/warm evidence and use the existing bounded invalidation helper; do not assert timing or partition behavior from a healthy replica-set run.
- Disabled mode still constructs an inert manager. Demonstrate zero streams and entries, and explain that a cache-free deployment can omit it entirely using the existing rollback reference.
- The example adds no library hot-path work and makes no latency or throughput claim. Counter and resource deltas establish execution behavior; a new performance benchmark is unnecessary.
