# Design

## Context

A checkout may lack valid ignore targets because CI creates them, contributors generate them on demand, or a recovery path creates them only after a failure. The presence of a file in one checkout is also insufficient evidence of a shared need.

## Goals / Non-Goals

Use the existing [development-environment capability](specs/development-environment/spec.md) as the contract. Limit implementation to the root ignore file and preserve the meaning and order of the retained rules.

## Decisions

### Use repository evidence for each removal

Review entries against tracked recipes, tooling configuration, CI and contributor guides. Check ignore-rule provenance in Git history for intentional local files and generated reports. Remove a template entry and its explanatory comments when these sources establish no current project use. The distribution boilerplate for eggs and setuptools metadata, PyInstaller entries, `.nox/`, alternate virtual environment names, and Pytype entries are removal candidates.

Use the following evidence when checking the less obvious retained entries.

| Paths                                                                     | Source                                                                                                                                                  |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `__pycache__/`, Python bytecode, native `.so`, and `target/`              | Active Python and native source trees and generated files in the checkout.                                                                              |
| `.venv`, `dist/`, `.tox/`, `.rust-tools/`, `node_modules/`, and test logs | Root `justfile`, `tox.ini`, and `.github/workflows/test.yml`.                                                                                           |
| `.hypothesis/`, `.pytest_cache/`, `.mypy_cache/`, and `.lycheecache`      | Current test and lint tools and their observed outputs.                                                                                                 |
| `/site`, `.cache`, `/.docs-artifact-*/`, and `/.docs-previous-*/`         | `CONTRIBUTING.md`, `docs/development/ci-validation-caches.md`, and `development/scripts/build_versioned_docs.py`.                                       |
| `.env`                                                                    | The optional real-server benchmark configuration in `CONTRIBUTING.md` and the environment-file handling in `justfile`.                                  |
| `.codex/` and the `.agents` and `.claude` blocks                          | Git history records local agent exclusions and explicit allowances for tracked OpenSpec skills and Claude settings.                                     |
| Benchmark and memory reports                                              | `.github/workflows/stream-cost-benchmark.yml`, the `test-memory` recipe in `justfile`, and reproduction instructions under `docs/development/reports/`. |

Copying a shorter generic template is quick but would require reconstructing project-specific exceptions. A deletion pass on the existing file keeps the verified rules in place. No prototype is required.

## Risks / Trade-offs

- Reviewing only the current checkout can miss optional, CI-only, and failure-path outputs. Use the evidence above and check representative paths that do not exist locally.
- Per-user Git excludes can mask the effect of a removal, and Git skips already tracked paths by default when checking ignore rules. Verify the revised file in an isolated repository and include paths covered by negation rules.
