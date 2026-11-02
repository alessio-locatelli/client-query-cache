# Proposal

## Why

The native extension is compiled with Cargo's default release profile, which leaves performance on the table for the cached-read hot path now implemented in Rust. A matched campaign on the unmodified source (recorded in `reports/rust-build-profile/summary.md`) shows whole-program optimization and profile-guided optimization (PGO) reduce native entry-point time and the end-to-end cached-read cost, while the other checklist options do not.

## What Changes

- Declare `lto = "fat"` and `codegen-units = 1` in the extension's release profile, so editable installs, source-distribution builds and release wheels all use them.
- Build each release wheel with Maturin's built-in profile-guided build (`maturin build --pgo`) on its own architecture: an instrumented wheel runs a MongoDB-free training workload, and the profile it records drives the final wheel. The source distribution and editable installs stay unprofiled.
- Add the training workload as a checked-in script, configured as Maturin's training command, that drives the native entry points the cache hot path uses.
- Record the campaign, including the rejected options, in `reports/rust-build-profile/summary.md` and link it from the native quality documentation.

## Capabilities

### New Capabilities

### Modified Capabilities

- `release-verification`: the release build produces profile-guided native extensions and fails visibly when any stage of the profile pipeline fails.

## Impact

- `native/shared-index/Cargo.toml`, `pyproject.toml` and `uv.lock` (training command and an empty `pgo` dependency group), `justfile` (`build`), a training script and a linker-wrapper fix under `scripts/`, the CI toolchain setup (the `llvm-tools` Rust component on build jobs).
- Release wheels are no longer byte-reproducible, because the recorded profile depends on the training run.
- Builds take longer, and each release build job needs network access for the training environment's pure-Python dependencies, as `just verify-release` already does.
