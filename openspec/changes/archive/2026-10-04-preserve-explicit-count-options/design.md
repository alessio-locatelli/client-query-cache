# Design

## Context

See proposal.md for the defect. Native count execution distinguishes option presence, including `hint=None`, while omitted skip and integer zero skip have equivalent results.

## Goals / Non-Goals

Preserve native options without adding database calls or a validation subsystem. General cache-hit handling of live server errors remains outside this fix.

## Decisions

Accept count bounds, collation, and hint through `**kwargs`, matching PyMongo, and forward the original kwargs unchanged on every native path. Keep the explicit session parameter for existing session bypass handling. This avoids exposing an omission token in the public signature.

Use one shared helper to separate supported cache options from unsupported extra options. Extra options retain existing direct execution. Cache shapes default skip to integer zero and collation to None; explicit values replace those defaults. This shares omitted skip and `skip=0` entries without rewriting native execution. A private token marks omitted limit and hint only inside cache shapes; it is never a native argument or public signature type. Explicit invalid bounds and `hint=None` remain distinct from omitted options. Collation objects use their documents in keys through the shared collation conversion also used by the other collection reads; native kwargs retain the original object.

Using an omission sentinel as a public parameter default would preserve execution but complicate signatures or require overloads. Keeping syntax-distinct keys for equivalent zero skip wastes entries. Native option validation remains with PyMongo/MongoDB.

## Risks / Trade-offs

- Bound and hint names now appear through kwargs, matching the driver's API rather than exposing implementation-only types.
- The key helper copies kwargs to identify extra options; benchmark key construction to verify the affected cost. No additional I/O is introduced.
