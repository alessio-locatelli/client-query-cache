## Why

The repository root holds sixteen tracked directories, most of them project-specific (`benchmarks/`, `examples/`, `reports/`, `research/`, `rules/`, `rule-tests/`, `scripts/`, `specifications/`, `native/`). A reader cannot tell which directories are conventional, which a tool requires at the root, and which merely accumulated there, and every new kind of artifact invites another root directory.

## What Changes

- Relocate every root-level directory that neither a tool nor the common project layout requires at the root, using the target layout in `design.md` D1. The root keeps `.agents/`, `.claude/`, `.github/`, `docs/`, `openspec/`, `src/`, `tests/`, and gains one directory, `development/`, for contributor tooling.
- **BREAKING** (contributors only): Python import paths and `python -m` entry points of benchmarks, research harnesses, and scripts gain the `development.` prefix (`design.md` D2); the Rust crate's manifest path, the example run commands, and the submodule path change accordingly. The installed package and its public API are unchanged.
- Add temporary transition code so that the performance-regression guard and the versioned-documentation assembler keep working while the compared or published revision predates the new layout, and remove it in a second pull request once its removal condition holds (`design.md` D5, D6).
- Update every configuration file, CI workflow, `justfile` recipe, test, script, active OpenSpec change, main spec, contributor guide, public guide, and in-repository link that names a moved path.
- Record the root-layout rule as a requirement so later additions follow it.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `development-environment`: adds the root-layout requirement.
- `usage-examples`: example location, run command, and discoverability link.
- `public-library-documentation`: Context7 exclusion scenario paths; reproducible assembly is limited to release tags with the current documentation layout.

## Impact

- Configuration: `pyproject.toml` (maturin, uv cache keys, vulture, slotscheck, ruff-extra-rules), `ruff.toml`, `mypy.ini`, `pytest.ini`, `.coveragerc`, `.gitignore`, `.gitmodules`, `.pre-commit-config.yaml`, `.prettierignore`, `.markdownlint-cli2.jsonc`, `.taplo.toml`, `_typos.toml`, `sgconfig.yml`, `.vulture_whitelist`, `justfile`.
- CI: `.github/workflows/{test,docs,publish,stream-cost-benchmark,dependency-automerge}.yml`, `.github/dependabot.yml`.
- Code: every module under the moved Python trees and `tests/` that imports, patches, runs, or reads a moved path; `scripts/ci_scope.py`, `benchmarks/stream_cost/guard_runner.py`, `benchmarks/stream_cost/guard_scope.py`, `scripts/build_versioned_docs.py`.
- Documentation: `AGENTS.md`, `CONTRIBUTING.md`, `docs/development/**`, `docs/user/**`, moved reports and example README, `native/shared-index/Cargo.toml` comments.
- OpenSpec: main specs listed above, and path references in the active changes `benchmark-worker-fault-recovery` and `complete-native-coverage`. Archived changes stay unchanged.
- Existing clones must re-initialize the moved submodule once.
