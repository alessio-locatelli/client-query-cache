## Context

The proof of concept subclasses `pymongo.MongoClient`, starts per-collection stream handling, and has no stable public contract. This change establishes the seam needed before core cache work.

## Goals / Non-Goals

**Goals:** Replace inheritance with composition, preserve caller ownership, and classify legacy behavior.

**Non-Goals:** This change does not implement cache storage, streams, or cached read operations.

## Decisions

- Build a manager around a supplied sync or async client and expose lightweight facades rather than subclassing driver types.
- Keep raw PyMongo collections available for unsupported operations and incremental migration.
- Treat the prototype as untrusted input: capture only behavior that is explicitly retained and test that boundary.

## Risks / Trade-offs

- [Existing users depend on an undocumented prototype detail] → Publish a migration map and do not silently emulate every internal behavior.
- [A facade closes a caller client] → Test ownership and close boundaries before adding cache features.

## Migration Plan

Inventory exports and tests, add the composed construction seam, deprecate/remove prototype entry points as documented, and verify raw fallback remains intact.
