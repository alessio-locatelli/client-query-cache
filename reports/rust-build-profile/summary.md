# Rust build profile measurements

Measured on 2026-11-02 at source revision `46edbdac` (v0.11.0) for the [optimize-native-release-build](../../openspec/changes/archive/2026-11-02-optimize-native-release-build/design.md) change. The [native quality guide](../../docs/development/native-quality.md#release-build) describes the resulting build; this report holds the evidence and the options that were rejected.

## Outcome

| Option                                               | Verdict        | Reason                                                                                                                     |
| ---------------------------------------------------- | -------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `lto = "fat"` with `codegen-units = 1`               | Retained       | About 4% less time per native call, 1.5% per cached read and 3% per invalidation; 14% smaller extension                    |
| Profile-guided optimization (PGO) in release wheels  | Retained       | About 18% less time per native call, 5% per cached read and 9% per invalidation, in total                                  |
| Thin LTO; two, four or sixteen code generation units | Rejected       | Thin LTO overlaps fat LTO within the noise (fat with one unit has the smallest binary); the unit counts alone give no gain |
| `opt-level = 2`                                      | Rejected       | No gain                                                                                                                    |
| `opt-level = "s"`                                    | Rejected       | 25% slower                                                                                                                 |
| `target-cpu` native, `x86-64-v2`, `x86-64-v3`        | Rejected       | No gain beyond noise alone or with LTO; wheels must run on every user's CPU                                                |
| `panic = "abort"`                                    | Rejected       | No gain beyond noise; a native panic would kill the host process instead of raising in Python                              |
| Post-link layout optimization (LLVM BOLT)            | Rejected       | No gain on top of PGO or of LTO                                                                                            |
| `-Z tune-cpu`, `-Z build-std`                        | Rejected       | Nightly-only; the repository supports one stable toolchain. Tune-CPU measured no gain and build-std was not measured       |
| Cross-language LTO                                   | Not applicable | The crate links no C or C++ code (`libc` and PyO3 are the only dependencies)                                               |
| `debug-assertions`, `overflow-checks`, `incremental` | Unchanged      | Release defaults apply; no environment variable or Cargo configuration overrides them                                      |
| Linker selection                                     | Not evaluated  | No runtime claim; release wheels already link with Zig                                                                     |

## Method

The host is an Intel Core i3-13100 (4 cores, 8 threads, `powersave` governor with `intel_pstate`) with 62 GiB of memory on Linux 7.2.13 and glibc 2.43, inside a Fedora Toolbx container that shares the host with other containers. The toolchain is rustc 1.99.1 (LLVM 23.1.1), Maturin 1.15.0 with Zig 0.15.2, PyO3 0.30.1 and CPython 3.14.7.

Candidates were compiled with `cargo build --release` using `CARGO_PROFILE_RELEASE_*` and `RUSTFLAGS`, then loaded by overlaying the extension onto a copy of the package. The final comparison instead uses the wheels that `maturin build --release --zig` produces on `main` and that `just build` produces on the branch.

`research/native_build_profile/measure.py` times 25 native workloads in one pinned process: process-local identity, find and namespace hits and misses, admissions with eviction, invalidation, key preparation, wire keys, cursor capture, shared-index lookups and publication, owner admission, the echo socket, the three call sequences the facade makes (hit, find miss, invalidation) and two workloads that the PGO training never runs (`snapshot` and `namespace_lifecycle`). Every cache workload first checks that one pass records exactly the hits and misses (or invalidations) it is named for, so a workload cannot silently exercise another path. Each run takes the median of 31 batches of at least 20 ms. `compare.py` alternates the builds in a shuffled order per round, pins each child to one core with address-space randomization off and a fixed hash seed, and reports the percentage by which a candidate reduces nanoseconds per operation relative to the baseline, paired within a round. The tables show the median over rounds with a 95% bootstrap interval (2,000 resamples) and the geometric mean over workloads. Positive numbers are improvements. Every matrix contains an A/A control: a copy of the baseline binary under another path.

`end_to_end.py` runs the pull-request performance guard's cases (`benchmarks.stream_cost.guard_workload`: cached `find_one` hits through the synchronous and asynchronous APIs, `find` admission and change-event invalidation, at 200-byte and 2,000-byte documents) against the MongoDB `mongo:9.0.4` replica set in a container limited to two CPUs and 1 GiB. Each cell is the fastest of three runs, and the matrix has nine rounds. The guard workload never took part in training, so it is the held-out check.

The first two matrices ran before the harness fixed the hash seed and disabled address-space randomization; their A/A controls bound the noise at about ±1–3%. Differences below that are not resolved.

## Representative comparisons

Seven rounds against Cargo's default profile found fat LTO/one codegen unit
improved the native-workload geometric mean by 4.1% [3.2, 5.5]; one unit alone
changed it −0.4% [−1.9, +0.2]. Fat/one unit yielded 1,224 KiB versus thin/one
unit's 1,294 KiB, with overlapping performance intervals. Compilation cost
14.0 seconds/374 MiB peak versus 8.1 seconds/404 MiB.

Fifteen shipping-wheel rounds found geometric mean improvements of 4.0%
[3.8, 4.2] for LTO alone and 18.4% [18.4, 18.6] for LTO+PGO; A/A was −0.1%
[−0.5, +0.3]. Nine held-out guard rounds found 1.5% [0.6, 2.9] and 5.1%
[4.3, 7.3] end-to-end. Admission intervals included zero; hits improved about
5%, invalidation about 9%. These are historical effects, not current guarantees.

BOLT added no resolved improvement over LTO/PGO while growing the extension
from about 1.3 MiB to 6.5 MiB and requiring relocation-preserving links and
additional instrumentation. CPU-target and panic-abort variants did not separate
from LTO alone beyond noise.

- The profile is keyed by function names, which embed crate hashes. A hand-written pipeline that built the instrumented wheel with the host linker left 869 functions of the Zig wheel without profile data, and the gain was 5% instead of 18%; cargo-zigbuild enables Cargo's unstable `target-applies-to-host` mode, which is the likely cause of the different hashes. Maturin's own `--pgo` builds both passes with Zig, so the release build uses it: its wheel was as fast as the corrected hand-written pipeline (+23.0% against +21.8% geometric mean on eight workloads, seven rounds), and it fails without writing a wheel when `llvm-profdata` is missing or the training command fails, which were both tried.
- Zig rejects rustc's separate `-u __llvm_profile_runtime` operand, so `scripts/zig-linker.sh` joins it into `-Wl,-u,…`.
- The measurements ran with Maturin 1.15.0. The shipped build needs 1.16.0, the first release that honors `pgo-dependency-group`, and its wheel measured the same (+20.8% against +21.1% geometric mean on nine workloads, seven rounds). uv adds the default `dev` group to the group Maturin exports, so `just build` sets `UV_NO_DEFAULT_GROUPS=1`; without it the training environment held 75 contributor packages instead of the wheel's three dependencies.
- `just build` takes 37.9 s with a 380 MiB peak, against 8.5 s and 404 MiB for `main`'s source distribution and wheel, because it compiles the extension three times and runs the training. The shipped extension is 5% smaller than `main`'s.

## Reproduction

Use separate installed release environments with matched source, compiler,
dependencies and training. The [historical commands](https://github.com/alessio-locatelli/client-query-cache/blob/243cbfb790766e9ee25b3ecced1ffe83e96d083c/reports/rust-build-profile/summary.md#reproduction)
reconstruct the variants from `46edbdac` and original training source. Later
workloads/telemetry policies differ. For current comparisons use
`research.native_build_profile.compare` and `end_to_end` with matched package
overlays, verified imported binaries and an identical-build A/A copy. Parent
allocator variables are not forwarded to measured children. Keep raw outputs
untracked; compare native and held-out complete-read results separately.

## Limitations

- One x86-64 host with frequency scaling and neighbouring containers; the intervals reflect that noise but not other machines.
- The ARM64 wheels follow the same pipeline and are verified by the ARM64 CI job, but their gain was not measured: [#401](https://github.com/alessio-locatelli/client-query-cache/issues/401) tracks it. Run the shipped-wheel comparisons of the reproduction section on an ARM64 host: the A/A controls give the noise, `lto_wheel` against `main_wheel` the effect of the Cargo profile, and `pgo_wheel` against `lto_wheel`, in the native workloads and end to end, the effect of profile guidance alone.
- The native workloads model the facade's call sequences rather than observe them; a native entry point that joins the hot path must be added to `scripts/pgo_training.py`.
- The end-to-end gain is bounded by the Python facade and PyMongo, which this change leaves untouched.
