# Proposal

## Why

The documentation mixes library-user guidance with maintainer notes, while the hosted quick start and examples send readers back to GitHub. A coherent content hierarchy and canonical topic ownership will let readers learn and evaluate the library on the site without maintaining parallel guides.

## What Changes

- Separate published library documentation in `docs/user/` from repository-only engineering documentation in `docs/development/`, including decisions and research.
- Build a complete site journey: Home, Getting started, Usage, Benchmarks, Examples, Reference, and Operations. Provide synchronous and asyncio quick starts and integration guidance within the site.
- Split the mixed architecture guide into practical public operations guidance and internal design documentation; retain all substantive operating limits and evidence.
- Keep one authoritative source for each detailed topic. Render example instructions and runnable source from their existing canonical files rather than copying them into site pages.
- Shorten README to a product introduction, essential prerequisites and consistency caveat, installation, and clear documentation entry points. Move detailed tutorials and benchmark analysis to the site.
- Repair repository links, preserve existing public page and heading destinations with site-local redirects, and align build/publication input selection with the new source layout.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `public-library-documentation`: Require a self-contained reader journey, explicit separation of public and development documentation, canonical content ownership, concise README, and continuity of published links. Replace the existing permission to use repository-only examples as the site's examples destination.

## Impact

Affected surfaces include `docs/`, README, CONTRIBUTING, `examples/README.md`, `zensical.toml`, documentation publication filters, `scripts/ci_scope.py`, and its existing tests. Existing locked Zensical tooling remains the starting point; any required authoring dependencies belong only to the docs group. Package behavior and public Python APIs do not change.

The active `add-real-usage-examples` change continues to own executable integrations and their verification. This change consumes delivered examples and preserves its requirement that `examples/README.md` lists run commands. It neither implements blocked integrations nor rewrites that change's artifacts.
