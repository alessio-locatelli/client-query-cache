# Proposal

## Why

Context7 guidance entered through its UI can drift from implemented behavior. A repository-owned configuration makes its usage rules reviewable alongside API and public documentation changes.

## What Changes

- Add root `context7.json` with the official schema reference and concise synchronous and asyncio usage rules.
- Select `docs/user` and the root README while excluding maintainer material and `docs/user/examples`, whose Pymdown snippet wrappers require site-build expansion.
- Require affected rules and public guides to change together with implementation through `AGENTS.md` and `CONTRIBUTING.md`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `public-library-documentation`: Add repository-owned Context7 usage rules and their maintenance contract.

## Impact

Only configuration, contributor/agent instructions, and OpenSpec documentation change. The existing documentation build and publication workflows remain unchanged. Complete integration examples remain on the hosted documentation site; including them in Context7 is outside this change.
