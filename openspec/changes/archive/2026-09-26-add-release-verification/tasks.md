## 1. Verify distributable artifacts

- [x] 1.1 Add a clean source and wheel build command; verify both artifacts are created from the locked project. (`just build`; verified with `just verify-release` producing `dist/client_query_cache-0.1.0.tar.gz` and the matching wheel.)
- [x] 1.2 Install the sdist and wheel into separate isolated environments and import documented sync and asyncio public APIs from each installation; verify missing or unusable files in either artifact fail the check. (`just verify-release` installs each artifact into its own `uv run --isolated --no-project` environment and runs `scripts/verify_release_artifacts.py`, which imports every name in `__all__` from `client_query_cache`, `client_query_cache.synchronous`, and `client_query_cache.asynchronous`; confirmed failing against a stale, differently-named artifact found in a local `dist/`.)

## 2. Verify release metadata safely

- [x] 2.1 Add version and optional tag-consistency checks without publishing credentials; verify mismatches fail with an actionable error. (`just verify-release <tag>` compares the tag, with its `v` prefix stripped, against `pyproject.toml`'s declared version; verified both a deliberate mismatch failing with an actionable message and a matching tag succeeding.)
- [x] 2.2 Add a non-publishing CI/manual release-verification job and documentation; verify it creates no external package or release state. (`.github/workflows/release-verification.yml` is a `workflow_dispatch` job with an optional `tag` input and `permissions: contents: read`; `test.yml`'s package job now also calls `just verify-release` instead of a duplicated inline check; documented in `CONTRIBUTING.md` under "Release verification" and in `docs/ci-validation-caches.md`.)

## 3. Code Quality

- [x] 3.1 Scan the entire file for edited or added tests (including pre-existing tests within the file) and ensure that the "Writing Tests" guidelines from `AGENTS.md` are applied, including test parametrization. (Touches no pytest files: this change adds a justfile recipe, a CI workflow, and a standalone verification script exercised directly via `just verify-release`, not pytest.)
- [x] 3.2 If you are Claude Code, confirm that you added no new prose to the code (all "why" explanations must go in the specs and commit bodies). OpenAI Codex is exempt from this rule because it understands the difference between garbage and valuable code comments. (Confirmed: no docstrings or comments were added to `justfile`, the workflow YAML, or `scripts/verify_release_artifacts.py`.)
