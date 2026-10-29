# Tasks

## 1. Toolchain selection

- [x] 1.1 Confirm the latest stable release from `https://static.rust-lang.org/dist/channel-rust-stable.toml` and pin it in a root `rust-toolchain.toml` with `profile = "minimal"`; delete `rust-version` from `native/shared-index/Cargo.toml`.
- [x] 1.2 Apply the Clippy suggestions reported by `just rust-lint` without the minimum version, then compare release machine code and native `OwnerIndex.store`/`ReaderIndex.lookup` timings with `main` built by the same compiler.
- [x] 1.3 Add the toolchain file to the maturin sdist `include` and the uv `cache-keys`; verify that the sdist contains it and builds under a rustup home without a default toolchain and with `RUSTUP_AUTO_INSTALL=0`.
- [x] 1.4 In `just setup-rust`, replace the version probes and the trailing component install with `rustup toolchain install --no-self-update` followed by `rustup component add rustfmt clippy llvm-tools-preview`, and install the Cargo quality tools with `cargo +<channel read with tomllib> install`.

## 2. Environments and automation

- [x] 2.1 Replace Fedora's `cargo`, `clippy`, `rust`, and `rustfmt` packages with `gcc` and `rustup` in the `Containerfile`, initialize the selected default, make the Rust and uv interpreter directories writable, and extend `scripts/check_dev_container.sh` to run as a non-root user with `RUSTUP_AUTO_INSTALL=0`, compare `rustc --version` inside and outside a checkout, build a probe crate, add rustfmt and Clippy, and run `uv python install`.
- [x] 2.2 Add the `rust` input to `.github/actions/setup-toolchain/action.yml` and pass `rust: "true"` from every job that compiles native code except `rust-static`, which uses `just setup-rust`; remove the workflow comments about runner-preinstalled Cargo; select Python, container, and guard validation for `rust-toolchain.toml` in `scripts/ci_scope.py` and `benchmarks/stream_cost/guard_scope.py`, and run the `rust-lint` hook for it.
- [x] 2.3 Add a weekly `rust-toolchain` Dependabot entry with the seven-day cooldown and validate it with `check-jsonschema --builtin-schema vendor.dependabot .github/dependabot.yml`.
- [x] 2.4 Update `CONTRIBUTING.md`, `docs/development/native-quality.md`, `docs/development/executable-version-updates.md`, `docs/development/ci-validation-caches.md`, `docs/development/performance-regression-guard.md`, and `docs/user/getting-started/installation.md`.
- [x] 2.5 Time `rustup toolchain install` in the CI logs of both runner architectures, time an `actions/cache` save and restore of the installed toolchain in a disposable workflow run, and record the measurements and the cache decision in `docs/development/ci-validation-caches.md`.

## 3. Code Quality

- [x] 3.1 Scan the entire file for edited or added tests (including pre-existing tests within the file) and ensure that the "Writing Tests" guidelines from `AGENTS.md` are applied, including test parametrization.
- [x] 3.2 Confirm that no new prose was added to the code; configuration rationale comments follow the development-environment override requirement.
