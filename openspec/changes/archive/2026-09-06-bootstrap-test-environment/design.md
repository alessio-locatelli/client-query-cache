## Context

Existing tests default to `localhost:27017` and a checked-in Compose service. Change streams need a replica set, but fast tests must remain available without containers.

## Goals / Non-Goals

**Goals:** Isolate test topology, separate test cost tiers, and prevent regressions from the measured production branch-coverage baseline.

**Non-Goals:** This change does not define cache semantics or hosted CI jobs.

## Decisions

- Use Testcontainers-Python to create a single-node replica set, initialize it, and wait for a writable primary. Docker Engine is the reference runtime; Docker API-compatible Podman is a documented local alternative.
- Mark tests explicitly. Default commands run unit tests; integration/e2e are explicit locally and become CI prerequisites later.
- Use a built-wheel subprocess for end-to-end evidence and separate its behavior assertion from coverage instrumentation.
- Combine coverage from applicable in-process tiers and set branch `fail_under` to the measured 81.10 percent baseline. Keep every importable production module in scope without coverage exclusions. The `implement-change-stream-coherency` change raises the gate to 100 percent when it implements the currently missing cache-coherency operations.

## Risks / Trade-offs

- [Container runtime unavailable] → Unit tests remain usable; integration/e2e preflight gives an actionable error.
- [Replica set is not primary yet] → The fixture polls with a bounded timeout before yielding clients.
- [The baseline leaves production branches uncovered] → Coverage reports keep every gap visible, new regressions fail the gate, and `implement-change-stream-coherency` owns closing the planned behavior gaps and raising the threshold to 100 percent.

## Migration Plan

Add markers and the measured coverage gate first, replace fixed-endpoint fixtures with Testcontainers, then classify and repair existing tests until every tier is reliable. Raise the gate to 100 percent when the planned cache-coherency behavior is implemented.
