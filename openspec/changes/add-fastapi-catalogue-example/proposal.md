# Proposal

## Why

The runnable catalogue demonstrates storage adapters but has no asyncio web-application lifespan or dependency-injection example. A product-content application provides an approachable use case with explicit boundaries around writes, fresh reads, and tenant filtering.

## What Changes

- Add a complete FastAPI catalogue program and hosted guide.
- Extend the example capability to include application integrations alongside existing library adapters.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `usage-examples`: application examples, web lifecycle, trusted tenant context, and product pagination.

## Impact

One new script and snippet guide, example catalogue and navigation, existing subprocess and type-check coverage. Example dependencies remain ephemeral; no package API or runtime dependency changes.
