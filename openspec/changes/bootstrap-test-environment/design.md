## Context

Existing tests default to `localhost:27017` and a checked-in Compose service. Change streams need a replica set, but fast tests must remain available without containers.

## Goals / Non-Goals

**Goals:** Isolate test topology, separate test cost tiers, and enforce complete production branch coverage.

**Non-Goals:** This change does not define cache semantics or hosted CI jobs.

## Decisions

- Use Testcontainers-Python to create a single-node replica set, initialize it, and wait for a writable primary. Docker Engine is the reference runtime; Docker API-compatible Podman is a documented local alternative.
- Mark tests explicitly. Default commands run unit tests; integration/e2e are explicit locally and become CI prerequisites later.
- Use a built-wheel subprocess for end-to-end evidence and separate its behavior assertion from coverage instrumentation.
- Combine coverage from applicable in-process tiers and set branch `fail_under` to 100; remove dead code rather than conceal ordinary paths.

## Risks / Trade-offs

- [Container runtime unavailable] → Unit tests remain usable; integration/e2e preflight gives an actionable error.
- [Replica set is not primary yet] → The fixture polls with a bounded timeout before yielding clients.

## Migration Plan

Add markers and coverage first, replace fixed-endpoint fixtures with Testcontainers, then classify and repair existing tests until every tier is reliable.
