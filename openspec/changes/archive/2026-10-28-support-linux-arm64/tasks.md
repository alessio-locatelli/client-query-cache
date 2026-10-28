# Tasks

The implementation scope is recorded in [design.md](design.md).
All acceptance references below use that document's decisions.

## 1. Platform boundary

- [x] 1.1 Update `SharedCacheServer` in `src/client_query_cache/shared.py` to admit the proposed architecture; parametrize the supported/unsupported platform cases in `tests/shared_cache/test_public.py` without starting an owner for invalid hosts. Confirm existing x86-64 errors and configuration validation remain meaningful.
- [x] 1.2 Check `memory.rs`, `index.rs`, `ring.rs` and `frames.rs` against the target's atomic size/alignment, native-endian encoding and version/fence assumptions. Record the conclusions in the feasibility report; an ordering or layout redesign requires a separate scope decision.

## 2. Target acceptance and distribution

- [x] 2.1 Add the design's ARM acceptance lane to `.github/workflows/test.yml`, with path selection through the existing scope mechanism. Run the ordinary native harness and existing local-core, synchronous, asynchronous and shared-cache real-server suites. Record runner architecture, full interpreter, tested revision, selected tests and duration in `reports/platform-portability/feasibility.md`; inspect logs for warnings and ensure an injected lane failure fails its required aggregate check.
- [x] 2.2 Extend `.github/workflows/release-verification.yml` and `.github/workflows/publish.yml` according to the per-architecture artifact decision. Keep `just verify-release` reusable; adjust its orchestration only where necessary. Demonstrate isolated ARM wheel/source verification, both architecture artifacts in the collected set, one sdist and publication blocked by any failed/cancelled architecture lane. Keep actual package publication outside this task.
- [x] 2.3 Update `docs/user/getting-started/installation.md` and the affected existing `context7.json` rule after native qualification. Review README and maintainer release guidance for platform/artifact assumptions and link to the canonical requirements instead of duplicating them. The delivered report must distinguish observed ARM results from the investigation's host-only evidence and retain any concrete blocker if qualification fails.

- [x] 2.4 Include `scripts/zig-linker.sh` in Python/package validation inputs and cover a linker-only edit in the existing scope-selection regression test, including its ARM64 outcome.
- [x] 2.5 Select the running architecture's wheel in `docs/user/benchmarks/shared-cache.md` while retaining the checkout version; verify the selected filename against the native x86-64 and ARM64 artifacts.

## 3. Code Quality

- [x] 3.1 Scan each entire edited or added test file, including its pre-existing tests, against the AGENTS.md Writing Tests rules and apply parametrization where test logic is shared.
- [x] 3.2 Confirm no new code prose was added if applying with Claude Code; OpenAI Codex is exempt (planning prepared by Codex).
