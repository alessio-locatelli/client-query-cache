# Tasks

The public barrier is deferred. These tasks replace the withdrawn implementation plan; completing them records
the documentation-only outcome and does not claim delivery of a barrier.

## 1. Preserve the decision and research

- [x] 1.1 Write `docs/decisions/defer-causal-invalidation-barrier.md` with the standard consistency contract,
      alternatives, reasons for deferral, and explicit low-priority integration research criteria. Verify that it
      treats direct/session-bound reads as database reads rather than immediate cache refreshes.
- [x] 1.2 Write `docs/causal-invalidation-barrier-research.md` with immutable PR #124 references, official sources,
      reported environment and measurements, concurrency counterexamples, unverified assumptions, and reproduction
      guidance. Verify that observations are not presented as current guarantees and that the independent asyncio
      deadline-inheritance finding remains visible.
- [x] 1.3 Link the decision and research from `docs/architecture.md`, withdraw the barrier delta, and declare
      `skip_specs: true`. Verify the diff changes no runtime files, tests, public API reference, or main specifications.

## 2. Code Quality

- [x] 2.1 Scan edited or added test files for the AGENTS.md Writing Tests rules. Not applicable: no tests change.
- [x] 2.2 If you are Claude Code, confirm no new prose was added to code. Not applicable: documentation authored
      by OpenAI Codex; no runtime code changes.
