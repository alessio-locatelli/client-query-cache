# Design

## Context

The guard job pipes the pull request's changed paths into its scope selector, which matches them against a fixed pattern list. Each compared revision is synchronized in its own worktree, so a selected run already builds and measures each revision's native extension; only the selection omits `native/`.

## Goals / Non-Goals

**Goals:**

- Every change that can alter the built native extension selects the guard.

**Non-Goals:**

- Selecting the guard for CI plumbing that the guard shares with other jobs, such as the setup-toolchain action; those jobs already validate it.

## Decisions

### Match every path under `native/`

The selector treats any path under `native/` as a guard input.

- Pros: a new build input, such as another source module or a build script, is selected without a pattern update. The prefix matches the native tier of the pull request scope selector and the `rust-lint` hook's file filter, so all three agree on what counts as native.
- Cons: edits to native test modules or the dependency policy file also run the guard, although they cannot change the built extension. The Python patterns accept the same cost for Python tests.

Alternative: match only build inputs (the crate manifest, `Cargo.lock`, and non-test sources, mirroring the uv cache keys). It saves guard runs on test-only native edits, but it must track the crate's test-file naming and every future build input; a missed input silently skips a hot-path comparison, which is the defect this change fixes. Rejected; no follow-up is needed.

## Risks / Trade-offs

- [The guard adds runner time to native-only pull requests and can lengthen a run, for example when runners are scarce] → Native changes also select the database-backed test jobs, which start no earlier than the guard and normally run several times longer, so the guard normally overlaps with them.
