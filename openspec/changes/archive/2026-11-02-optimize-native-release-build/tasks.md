# Tasks

## 1. Release profile

- [x] 1.1 Add `[profile.release]` with `lto = "fat"` and `codegen-units = 1` to `native/shared-index/Cargo.toml`, each preceded by the repository's `The default is … We override it because …` comment with the Cargo profile documentation URL. Verify with `cargo build --release --locked --manifest-path native/shared-index/Cargo.toml --features python` and `just rust-models` (compare its duration with `main`).

## 2. Training workload

- [x] 2.1 Create `scripts/pgo_training.py`: the workload definitions (no Faker or MongoDB; deterministic documents from `random.Random`) plus a `main()` that runs each workload for a fixed number of passes. Cover every call listed in design D4. Verify with `.venv/bin/python scripts/pgo_training.py`.
- [x] 2.2 Add `tests/test_pgo_training.py`, one parametrized unit test per declared workload running one pass. Verify with `just pytest -- tests/test_pgo_training.py`.
- [x] 2.3 Make `research/native_build_profile/measure.py` import its workloads from `scripts/pgo_training.py` and keep only the held-out additions there. Verify by running the module once with `--workloads identity_hit_small`.

## 3. Release pipeline

- [x] 3.1 Set Maturin's `pgo-command` (`python scripts/pgo_training.py`) and `pgo-dependency-group` (an empty `pgo` group) in `pyproject.toml`, raise the `maturin[zig]` build minimum to 1.16.0 (the first release honoring the group) and refresh `uv.lock`, set `UV_NO_DEFAULT_GROUPS` for the PGO build, reduce `scripts/zig-linker.sh` to the `-u` operand join, and change `just build` to write the source distribution with `maturin pep517 write-sdist` and the wheel with `maturin build --release --pgo --zig …`. Verify `just build` leaves one sdist and one wheel in `dist/`, `just verify-release` passes, and a toolchain without `llvm-profdata`, or a failing training command, produces a failure and no wheel.
- [x] 3.2 Add an optional `rust-components` input to `.github/actions/setup-toolchain/action.yml` and pass `llvm-tools` in each job that runs `just verify-release` or `just build`. Verify with `just ci-lint` and `grep -rn 'verify-release\|just build' .github/workflows`.

## 4. Evidence and documentation

- [x] 4.1 Write `reports/rust-build-profile/summary.md` from the campaign: method, build matrix, results, rejected options with reasons, held-out and never-trained path comparison, existing-versus-added test timing against `main`, reproduction commands, and the ARM64 ticket. Verify every command in it runs as written.
- [x] 4.2 Document the release profile and pipeline in `docs/development/native-quality.md` (linking the report instead of repeating results), the new component in `CONTRIBUTING.md` if it lists release prerequisites, and add the user-visible entry under "Unreleased" in `CHANGELOG.md`. Verify with `just docs-build`.

## 5. Code Quality

- [x] 5.1 Scan the entire file for edited or added tests (including pre-existing tests within the file) and ensure that the "Writing Tests" guidelines from `AGENTS.md` are applied, including test parametrization.
- [x] 5.2 If you are Claude Code, confirm that you added no new prose to the code (all "why" explanations must go in the specs and commit bodies). OpenAI Codex is exempt from this rule because it understands the difference between garbage and valuable code comments.
