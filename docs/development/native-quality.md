# Native Rust quality checks

Run `just setup-rust` to install the pinned Cargo quality tools into the ignored
`.rust-tools/` directory and provision the selected Python through uv. The command
uses Cargo's existing-install detection and does not install OS packages.

The contributor image supplies Rust formatting and Clippy. Outside that image,
use the official [Rust installation guide](https://rust-lang.org/tools/install)
and [rustup components guide](https://rust-lang.github.io/rustup/concepts/components.html)
for `rustfmt` and `clippy`. Missing prerequisites fail visibly.
The pinned quality tools require Rust 1.95 or newer; this does not raise the
native library's declared minimum compiler version.

| Command            | Enforcement                                                                                                                                    |
| ------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `just rust-lint`   | Formatting, Clippy/compiler warnings, unused dependencies and unlinked files, dependency advisories, licenses, duplicate versions, and sources |
| `just format`      | Repairs Rust formatting alongside repository formatting                                                                                        |
| `just rust-tests`  | Native unit tests and bounded Loom concurrency models                                                                                          |
| `just rust-models` | Bounded Loom concurrency models alone                                                                                                          |

The local hooks run native static checks, and `just lint` includes them through
Prek. Native dependency policy lives in `native/shared-index/deny.toml`. Compiler
warnings fail validation in the shipped Python configuration. Harnesses that omit
Python consumers retain a narrowly scoped, explained unused-code exception.
Dead-code analysis does not prove that every runtime path is used; DRY and unsafe
code safety still require review.

CI runs **Rust static checks** once, followed by **Rust tests and concurrency models**.
Configure both as required checks, together with **Prek** and
**Prettier, Markdownlint, and OpenSpec**: a skipped dependent job cannot substitute
for its failed prerequisite. Python compatibility jobs retain their interpreter
matrix without repeating the interpreter-independent Cargo suite.

Python coverage does not measure native instructions. Native coverage enforcement
is tracked separately in [issue #328](https://github.com/alessio-locatelli/client-query-cache/issues/328).
