# Native Rust quality checks

## Rust toolchain

`rust-toolchain.toml` selects one exact stable Rust release with rustup's minimal profile. In the checkout and in source distributions, rustup installs that release on first use, so development, CI, release, and source builds use the same compiler. Only the selected release is tested and supported. The native crate declares no minimum Rust version; older compilers are not necessarily incompatible, but compatibility with them is not maintained. Cargo installations without rustup ignore the selection.

The contributor image and the GitHub-hosted runners provide rustup; CI jobs that compile native code install the selected release before building. Elsewhere, install rustup with the official [Rust installation guide](https://rust-lang.org/tools/install). Dependabot proposes each newer stable release, including patch releases; see [executable version updates](executable-version-updates.md).

## Commands

Run `just setup-rust` to install the selected toolchain with the `rustfmt`, `clippy`, and `llvm-tools-preview` [components](https://rust-lang.github.io/rustup/concepts/components.html), install the pinned Cargo quality tools into the ignored `.rust-tools/` directory, and provision the selected Python through uv. The command reuses existing rustup and Cargo installations and does not install OS packages. Missing prerequisites fail visibly.

| Command              | Enforcement                                                                                                                                    |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `just rust-lint`     | Formatting, Clippy/compiler warnings, unused dependencies and unlinked files, dependency advisories, licenses, duplicate versions, and sources |
| `just format`        | Repairs Rust formatting alongside repository formatting                                                                                        |
| `just rust-tests`    | Native unit tests and bounded Loom concurrency models                                                                                          |
| `just rust-coverage` | Combined production line/function coverage from native and Python tests                                                                        |
| `just rust-models`   | Bounded Loom concurrency models alone                                                                                                          |

The local hooks run native static checks, and `just lint` includes them through
Prek. Native dependency policy lives in `native/shared-index/deny.toml`. Compiler
warnings fail validation in the shipped Python configuration. Harnesses that omit
Python consumers retain a narrowly scoped, explained unused-code exception.
Dead-code analysis does not prove that every runtime path is used; DRY and unsafe
code safety still require review.

The yanked-release warning from installing the pinned `cargo-shear` tool is tracked in
[#345](https://github.com/alessio-locatelli/client-query-cache/issues/345).

CI runs **Rust static checks** once, followed by **Rust tests and concurrency models**.
The `main` ruleset requires both checks from GitHub Actions, together with **Prek**
and **Prettier, Markdownlint, and OpenSpec**. A skipped dependent job cannot
substitute for its failed prerequisite. Python compatibility jobs retain their interpreter
matrix without repeating the interpreter-independent Cargo suite.

Python coverage does not measure native instructions. Native coverage enforcement
is tracked separately in [issue #328](https://github.com/alessio-locatelli/client-query-cache/issues/328).

## Native coverage

`just rust-coverage` requires the tools installed by `just setup-rust`. It combines
Rust unit tests and container-free shared-cache Python tests against an
instrumented wheel. Only the wheel enables the Python feature, so the module
initialization export is measured once. The command clears previous profiles and crate artifacts before each run,
while retaining compiled dependencies. It enforces 100% line and function
coverage and prints missing lines. Loom remains a separate correctness check.

The measured production modules are `clock`, `echo`, `frames`, `hash`, `index`,
`key_encoder`, `memory`, `python`, `relay`, and `ring`, including the Python binding bodies.
`lib` and `sync` contain only module declarations and imports. Test bodies and
helpers live in test-only files excluded by cargo-llvm-cov's
[standard source selection](https://github.com/taiki-e/cargo-llvm-cov#exclude-file-from-coverage);
no production file is excluded. Stable instrumentation does not measure branch
coverage.

The wheel and locked test dependencies are installed in a fresh virtual
environment under `/tmp/agents/`. Its Python runs pytest directly, leaving the
ordinary editable installation unchanged. The command prints the temporary
artifact directory, including the Python test log, for diagnosis.

### Generated wrapper measurement

[PyO3 #6545](https://github.com/PyO3/pyo3/issues/6545) tracks misleading coverage
entries for generated `#[pymethods]` helpers. The issue contains the minimal
reproduction, verified versions, diagnostic evidence, and upstream fix candidate.
The native coverage command uses the unmodified cargo-llvm-cov report and applies
no generated-wrapper exception.
