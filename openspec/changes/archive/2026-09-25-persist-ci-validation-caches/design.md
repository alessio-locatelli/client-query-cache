# Design

## Context

CI uses separate Prek, formatting, Python, and benchmark jobs. Dependency caches already exist for uv, npm, and Prek hook environments. Tool result caches live in the checkout or under `node_modules` and are lost with each hosted runner.

## Goals / Non-Goals

**Goals:** Persist all reusable caches written by validation tools and make every cache's ownership and storage path explicit.

**Non-Goals:** Reuse final pass/fail results, cache test databases or coverage files, or cache generated environments such as `.venv` and `node_modules`.

## Decisions

- Keep uv, npm, and Prek environment caches on their existing integrations. Add job-local GitHub cache entries for Lychee, Ruff, Prettier, MyPy, Pytest, and Hypothesis.
- Restore Prettier's cache after `npm ci`, which recreates `node_modules`. Use the default Prettier cache location and content-based cache strategy, which is safe across checkout timestamp changes.
- Scope result cache keys by OS, runtime/tool version, dependency/configuration hashes, and commit SHA. Restore the latest compatible snapshot with a prefix. The changing SHA lets each new commit save newly learned state rather than freezing a fixed cache key.
- Keep caches advisory: every validator executes and computes its own invalidation. Do not cache mutable external state such as a running MongoDB instance or benchmark output as a validation shortcut.

## Risks / Trade-offs

- [Cache storage grows with commits] → GitHub's cache eviction handles older snapshots; cache paths are limited to each tool's own state.
- [External link responses change] → Lychee enforces its configured 14-day maximum age and rechecks expired entries.
- [GitHub cache scope limits cross-branch reuse] → New branches can start cold; checks still run correctly.
