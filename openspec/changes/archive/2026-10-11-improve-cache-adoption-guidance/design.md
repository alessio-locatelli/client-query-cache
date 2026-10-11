# Design

## Context

See [proposal.md](proposal.md) for motivation. Canonical public contracts already cover asynchronous invalidation, per-worker ownership, and bypass reasons. Examples use PEP 723 dependencies and run through one parametrized subprocess test.

## Goals / Non-Goals

The application excerpt should be approximately 50–100 lines. Verification may be longer and uses the same application through FastAPI's in-process client. No authentication system, shared cache, benchmark harness, or production failure injector is introduced.

## Decisions

### One source for the application and its executable verification

Use snippet regions in a new self-contained script, showing only its application region on the compact guide. Its self-check seeds and cleans a dedicated database outside the lifespan, so adopting the lifespan does not delete data. Use the existing subprocess-test parametrization and example type-check loop.

Alternative: put verification in a separate test module. That shortens the script but duplicates dependency provisioning and makes the documented run command unable to demonstrate behavior. Alternative: shorten the catalogue itself. That removes useful tenant, pagination, and rollout coverage. Neither requires further research; the chosen approach is exercised by task 2.

Application paths reuse one client, pool, manager and cached collection. A hit adds local lookup/decoding work; a miss adds the existing database read and admission. Metrics inspect public snapshots. The example adds no library hot-path work; timing it would measure demonstration plumbing rather than a runtime change, so no new performance claim is made.

### Decision guidance links rather than copies contracts

Add an adoption page under getting started, a worked eligibility page under usage, and a permission exercise under operations. Detailed research remains where it is. Extend the existing deployment capacity section with a worked multi-worker estimate and distinguish BSON budget from observed process memory.

Alternative: consolidate all existing guides into one adoption page. That reduces navigation but duplicates canonical contracts and obscures task-specific reference material. No research is necessary. A calculator is excluded because the accepted audit assessment found no validated economic model.

### Safe permission exercise

Describe a fresh manager using a custom read role that permits collection reads and metadata but omits database changeStream privileges. Grant the missing privilege through an administrator and observe the same manager retry on later reads. Keep commands scoped to a disposable database and a placeholder principal; link MongoDB's official role-management documentation. Network/failover timings stay in the active fault-recovery change.

Alternative: revoke permissions on a running production principal. This is disruptive and existing authenticated streams can delay observable revocation, making the lesson ambiguous. Alternative: package an authenticated topology harness solely for this guide. It adds infrastructure beyond this documentation change. Neither alternative needs research; task 3 verifies the guide's commands on an isolated authenticated replica set if available and otherwise records the limitation without claiming an observed timeline.

## Risks / Trade-offs

- An invalidation may arrive before the first post-write read: the check accepts immediate convergence and the guide illustrates both possibilities.
- Startup and scheduling affect counters: seed before startup, use exact-identity reads, and bound readiness/convergence polling rather than sleeping for an assumed recovery time.
- An unauthenticated compact app is unsuitable for public exposure: use only the in-process self-check and direct adopters to the catalogue's access-control integration.
- Version compatibility evidence is finite: recommend reproducible dependencies and application checks without guaranteeing safety from lockfiles or CI.
