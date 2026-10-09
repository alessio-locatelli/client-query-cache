# Design

## Context

See [proposal.md](proposal.md) for motivation and scope. BSON envelope values and framework state are dynamically typed; public read methods still declare concrete return types.

## Decisions

Keep public signatures and helper parameters precise. Use targeted type ignores at cache payload consumers and PyMongo forwarding sites where existing annotations cannot express the established runtime contract. Retain annotated locals for values consumed by subsequent logic, and forward arguments directly where annotations suffice. Do not add assertions, conversions, wrapper calls, or copied containers merely to satisfy a type checker.

Returning `Any` throughout the public API would avoid checker errors but lose caller guarantees. Typed locals used only for an immediate return add bindings and redundant-assignment suppressions without improving the return contract. Runtime assertions would narrow types but add repeated checks and change failure behavior. None of these alternatives needs further research.

## Resource costs and evidence

Cache lookup, decoding, admission, invalidation, and database round trips keep their existing complexity. Removing casts eliminates constant per-read calls without adding allocations or I/O; BSON decoding and cache bookkeeping remain expected dominant costs. Compare representative warm reads before and after, including a call profile, and record measurements and reproduction commands in the commit body. Raw diagnostics stay untracked.

## Risks

Static adaptations rely on the same decoded-value and driver contracts as the removed casts. Existing sync/async read, projection, cursor, and example tests cover those contracts; strict type checking protects declared return types. No data migration is needed; rollback is a commit revert.
