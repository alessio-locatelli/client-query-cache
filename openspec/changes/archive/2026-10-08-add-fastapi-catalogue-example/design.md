# Design

## Context

See [proposal.md](proposal.md) and the [delta](specs/usage-examples/spec.md). Existing scripts use PEP 723 dependencies and an editable working-tree source; `tests/examples/test_examples.py` runs a fixed list of subprocesses, while `just typecheck-examples` discovers scripts automatically. `eve_example.py` already demonstrates owner filtering, pagination and raw mutation checks. The new example's additional value is asyncio application resource ownership, not a claim that these patterns are otherwise absent.

## Goals / Non-Goals

Keep the application storage boundary explicit and the program executable without a running HTTP server. This is a demonstration of cache use, not a complete authentication implementation, booking system, deployment template, or framework adapter added to the package.

## Decisions

### Application lifespan and a small repository

Create `examples/fastapi_catalogue_example.py`. Its `FastAPI(lifespan=...)` context constructs `AsyncMongoClient` and the async manager in that order, yielding an application-state repository and closing in reverse order. Dependencies return the repository and the authenticated principal; handlers do not pass cached collections throughout the application. Use description reads and an ordered `find(...).sort(...).skip(...).limit(...).to_list()` page. Validate page sizes so the demonstration cannot request an unbounded page.

Use a product business identifier shared across tenant documents, with distinct MongoDB `_id` values, so both item and page predicates can demonstrate tenant filtering. A PATCH uses a raw collection with majority write/read concerns and an explicit causally consistent session for its update and response read. This illustrates immediate read-after-write without claiming that raw reads refresh the cached view. All calls in that workflow carry the same session; ordinary catalogue GETs do not.

FastAPI's [lifespan guidance](https://fastapi.tiangolo.com/advanced/events/) supplies the lifecycle pattern. Constructing clients globally risks event-loop and process-lifecycle mismatch; constructing them per request repeatedly pays stream startup cost. A generic collection-forwarding adapter would add unnecessary package architecture for explicit application-owned storage. No additional research is needed; task 1.1 applies the pattern.

### Safe demonstration identities

The principal dependency defaults to an authorization failure. Only the in-process self-check installs a labeled demonstration override selecting from two fixed principals; it does not accept arbitrary tenant identifiers as trusted identity. Define one principal's write permission explicitly and check it before entering repository mutation. Validate response content for both tenants, absent identity, forbidden mutation, and a request attempting to select another tenant. The guide tells adopters to supply their existing trusted authentication dependency and links official framework guidance.

Reading tenant identity directly from a query parameter is shorter but would teach a broken authorization boundary. Building a token issuer and authentication database distracts from cache integration and adds unrelated dependencies. Demonstration overrides are supported by [FastAPI's testing guidance](https://fastapi.tiangolo.com/advanced/testing-dependencies/). No authentication research is necessary; task 1.2 covers the isolation and permission assertions.

### Self-check and ephemeral dependencies

Use `TestClient` as a context manager to drive the lifespan, following [FastAPI's event-testing guide](https://fastapi.tiangolo.com/advanced/testing-events/). A local no-network probe verified HTTP handling and async manager closure with FastAPI 0.143.0, Starlette 1.7.0 and httpx2 2.13.1. The current Starlette test client warns when using its deprecated httpx path; declare `fastapi>=0.143.0` and `httpx2>=2.13.1` in script metadata rather than introducing that warning. Add no Uvicorn requirement for the documented self-check.

The run uses an explicitly named disposable example database and the catalogue's existing reset warning. Seed tenant content through the application's loop, warm item and page reads, report public manager hit statistics, update through HTTP, and poll a new GET within five seconds for invalidation. Missing evidence raises a named `SystemExit` failure. Perform database setup and cleanup on the same application loop as its client. Check the retained manager's public snapshot after lifespan exit.

An externally served app would better resemble deployment but needs ports, shutdown orchestration and another process merely to exercise request handling. An async ASGI transport needs separate lifespan orchestration. The context-managed test client provides both without new infrastructure. Real-replica-set behavior and script type compatibility remain to be exercised in tasks 1.2 and 1.3; they do not change the chosen architecture.

### Discovery without duplication

Add `docs/user/examples/fastapi.md` as a short explanation plus a snippet of the canonical script. Place the catalogue application before policy/task-state adapters in `examples/README.md` and the existing Examples navigation. Link the canonical cursor, consistency and capacity guides instead of repeating their catalogues. Existing application/library introductions need inclusive wording under the modified example requirement.

## Risks / Trade-offs

- Majority visibility matters for acknowledged setup and update writes; use the same concerns in seeded data and the demonstrated write workflow.
- Demonstration identities are intentionally not deployable authentication. Keep overrides confined to the self-check and reject unauthenticated requests in the app itself.
- Polling proves eventual invalidation, not a freshness bound. Preserve the bounded demonstration and explicit caveat.
- The example adds no library hot-path work and makes no throughput claim; no performance benchmark is necessary for this change.
