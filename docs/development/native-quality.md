# Native Rust quality checks

## Rust toolchain

`rust-toolchain.toml` selects one exact stable Rust release with rustup's minimal profile. In the checkout and in source distributions, rustup installs that release on first use, so development, CI, release, and source builds use the same compiler. Only the selected release is tested and supported. The native crate declares no minimum Rust version; older compilers are not necessarily incompatible, but compatibility with them is not maintained. Cargo installations without rustup ignore the selection.

The minimal profile contains only the compiler, the standard library, and Cargo. It is chosen so that jobs and users who only build the package, including builds from the source distribution, do not download formatting, lint, coverage, or documentation components. `just setup-rust` adds the development components where they are used.

The contributor image and the GitHub-hosted runners provide rustup. CI jobs that compile native code run `rustup toolchain install` before building instead of letting Cargo's first call install the release: rustup 1.29.2 reports such first-use installations with a warning, and the explicit step fails on a runner without rustup instead of silently using any other Cargo installed there. Each of these jobs downloads the release; [Rust toolchain downloads](ci-validation-caches.md#rust-toolchain-downloads) gives the measured cost and why it is not cached. Elsewhere, install rustup with the official [Rust installation guide](https://rust-lang.org/tools/install). Dependabot proposes each newer stable release, including patch releases; see [executable version updates](executable-version-updates.md).

## Release build

The extension's release profile uses whole-program link-time optimization and a single code generation unit; every build route inherits it from `src/shared-index/Cargo.toml`, including editable installs and source distributions. Release wheels are additionally profile-guided. `just build` writes the source distribution, then runs `maturin build --pgo`: Maturin builds an instrumented wheel, installs it into a temporary environment, runs the `pgo-command` from `pyproject.toml` (`development/scripts/pgo_training.py`), merges the recorded profile with `llvm-profdata`, and compiles the shipped wheel with that profile, using Zig in both builds. The recording happens on each architecture's own runner, so no profile is stored in the repository and none can go stale. The training workload needs no MongoDB; it drives the native entry points that cached reads, admissions (with and without the optional retention limits), invalidation, key preparation and the shared owner use: owner admission and publication, reader lookups, recency touches and the admission queue. A function that the workload never calls is optimized for size, so extend the workload when a native entry point joins the hot path. Admission workloads for opt-in features run for a fifth of the default time: at the full share their counts raised the profile total by about a quarter, which moved the hot threshold and slowed the default paths that sit near it. Their hit workloads run for the full time, because a hit executes few blocks and adds little to the total, while an entry point that stays below the profile's cold threshold is optimized for size. The training tests run each cache-core workload once per telemetry policy and each primitive workload once, which makes a signature change fail the suite before a release build does.

Maturin fails the build instead of emitting an unprofiled wheel when a stage fails, and it reports a missing `llvm-profdata` with the `rustup component add llvm-tools` command (`just setup-rust` already adds the component). Profile-guided wheels are not byte-reproducible, because the recorded counts vary between training runs.

Cache-core workloads train both telemetry policies: 80% of each workload's timed allocation uses disabled telemetry and 20% uses enabled telemetry. This preserves each workload's total allocation and its existing admission weighting. Setup and enabled counter verification add fixed passes outside those allocations. New cache-core workloads train both policies unless explicitly listed as core-policy-independent in `development/scripts/pgo_training.py`. The [telemetry measurement report](./reports/opt-in-telemetry/summary.md#pgo-training-comparison) records the compared mixes and their limits.

[The measurement report](./reports/rust-build-profile/summary.md) records measured build trade-offs, rejected options and the method.

## Comparing native measurements

Use repeated matched acquisitions, independent builds of identical source and
an identical-binary A/A control when separating source effects from PGO/build
variation. Equal-length import paths remove one layout difference; they do not
make allocator state identical. Confirm which environment variables reach timing
children: `development.research.native_build_profile.compare` and `end_to_end` construct
restricted child environments and do not forward parent allocator controls.
Only the fixed import path, hash seed and executable path, plus an optional
`LLVM_PROFILE_FILE`, reach these children. Parent `PYTHONMALLOC`, `MALLOC_CONF`,
`MALLOC_ARENA_MAX` and `LD_PRELOAD` settings therefore cannot select an allocator
for these comparisons. Use these runners for the default allocator; allocator
comparisons require a collector that records and forwards the selected controls.

Keep the statistic explicit: a median of within-round percentage changes need
not equal the ratio of the two medians. Time complete operations separately
from profiles/counters, whose boundaries and overhead differ. A microbenchmark
difference alone does not establish a production defect.

On shared or virtualized hosts, control layout and interference before comparing small effects:

- Build each variant in its own Cargo target directory. Worktrees of the same package share fingerprints in one target directory, so an output can belong to another variant. Clean unprofiled builds with `--remap-path-prefix` reproduced byte for byte; an incremental rebuild did not, and PGO-trained wheels never do.
- `compare.py` rewrites each extension as a new file before every child run. With address-space randomization off, a fixed file copy otherwise keeps its page-cache pages, and an identical copy was slower in six of seven rounds (geometric mean −6.6%).
- Move other processes off the measured CPU (`taskset -a -p -c` with the other CPUs), and on hosts with bursts lasting seconds select `--statistic p10_ns` with `--repeats 2` so a burst counts only when it hits every repeat.

The [crate-replacement evaluation](./reports/rust-crate-replacements/summary.md) records the controls that motivated these settings.

## Shared key hash

`hash.rs` uses `rapidhash`'s portable v3 algorithm with a fixed secret, and owners and readers must agree on its output. A pinned known key in `hash/tests.rs` fails when a dependency update changes that output; raise `LAYOUT_VERSION` in `index.rs` and update the pinned value together, so that mappings of the old layout are refused instead of read with another hash. The full-hash collision pairs in `index/tests.rs` must then be found again; the [evaluation report](./reports/rust-crate-replacements/summary.md#reproduction) gives the search.

## Commands

Run `just setup-rust` to install the selected toolchain with the `rustfmt`, `clippy`, and `llvm-tools-preview` [components](https://rust-lang.github.io/rustup/concepts/components.html), build the pinned Cargo quality tools with that release into the ignored `.rust-tools/` directory, and provision the selected Python through uv. The command reuses existing rustup and Cargo installations and does not install OS packages. Missing prerequisites fail visibly.

| Command              | Enforcement                                                                                                                                    |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `just rust-lint`     | Formatting, Clippy/compiler warnings, unused dependencies and unlinked files, dependency advisories, licenses, duplicate versions, and sources |
| `just format`        | Repairs Rust formatting alongside repository formatting                                                                                        |
| `just rust-tests`    | Native unit tests and bounded Loom concurrency models                                                                                          |
| `just rust-coverage` | Combined production line/function coverage from native and Python tests                                                                        |
| `just rust-models`   | Bounded Loom concurrency models alone                                                                                                          |

The local hooks run native static checks, and `just lint` includes them through
Prek. Native dependency policy lives in `src/shared-index/deny.toml`. Compiler
warnings fail validation in the shipped Python configuration. Harnesses that omit
Python consumers retain a narrowly scoped, explained unused-code exception.
Dead-code analysis does not prove that every runtime path is used; DRY and unsafe
code safety still require review.

The yanked-release warning from installing the pinned `cargo-shear` tool is tracked in
[#345](https://github.com/alessio-locatelli/client-query-cache/issues/345).

CI runs **Rust static checks** once, followed by **Rust tests and concurrency models**;
both are [required checks](../../CONTRIBUTING.md#required-checks). Python compatibility jobs retain their interpreter
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

The measured production modules are `array`, `clock`, `frames`, `hash`, `index`,
`key_encoder`, `keys`, `local_cache`, `memory`, `python`, and `ring`, including the Python binding bodies.
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
