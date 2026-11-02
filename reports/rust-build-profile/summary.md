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

## Cargo profile

Seven rounds against the default release profile (`lto` off, 16 code generation units). Every LTO variant gains 3–5%, their intervals overlap, and a single unit alone gains nothing. Fat LTO with one unit was chosen because it yields the smallest extension and is the configuration the later steps were built on.

| Configuration | Geometric mean change, % [95% interval] | Extension size | Peak RSS |
| ------------- | --------------------------------------: | -------------: | -------: |
| cgu1          |                       -0.4 [-1.9, +0.2] |       1368 KiB |    -0.1% |
| cgu2          |                       +1.3 [+1.1, +2.0] |       1484 KiB |    +0.0% |
| cgu4          |                       -0.2 [-0.4, +2.2] |       1505 KiB |    +0.1% |
| thin          |                       +2.9 [+1.5, +4.5] |       1506 KiB |    +0.1% |
| fat           |                       +3.3 [+1.4, +4.1] |       1254 KiB |    -0.5% |
| thin_cgu1     |                       +4.7 [+4.3, +5.9] |       1294 KiB |    -0.2% |
| fat_cgu1      |                       +4.1 [+3.2, +5.5] |       1224 KiB |    -0.2% |
| thin_cgu16    |                       +4.1 [+3.2, +4.5] |       1506 KiB |    +0.0% |
| fat_cgu16     |                       +3.6 [+2.3, +4.2] |       1254 KiB |    -0.1% |
| opt2          |                       -0.6 [-3.8, +1.8] |       1556 KiB |    -0.1% |
| opts          |                    -25.5 [-26.3, -23.0] |       1589 KiB |    -0.2% |
| opt2_fat_cgu1 |                       +3.9 [+3.3, +4.0] |       1199 KiB |    -0.1% |
| control       |                       -0.4 [-1.0, +2.4] |       1569 KiB |    -0.0% |

Names: `cgu*` is `codegen-units`, `thin` and `fat` are `lto`, `opt2` and `opts` are `opt-level` 2 and `"s"`, `control` is the A/A copy. Compiling with `lto = "fat"` and one unit took 14.0 s and 374 MiB peak memory against 8.1 s and 404 MiB.

## CPU target, panic strategy and tune-CPU

Nine rounds against the default release profile. `native` is `-C target-cpu=native`, `v2` and `v3` are `x86-64-v2` and `x86-64-v3`, `abort` is `panic = "abort"`, and `tune` is `-Z tune-cpu=native` on the pinned stable compiler through `RUSTC_BOOTSTRAP=1`. The `fat_cgu1_*` rows add the option to fat LTO with one unit.

| Configuration    | Geometric mean change, % [95% interval] | Extension size | Peak RSS |
| ---------------- | --------------------------------------: | -------------: | -------: |
| fat              |                       +2.3 [+0.8, +7.4] |       1254 KiB |    -0.5% |
| fat_cgu1         |                       +5.0 [+3.2, +9.2] |       1224 KiB |    -0.3% |
| thin_cgu1        |                       +4.6 [+1.4, +7.0] |       1294 KiB |    -0.1% |
| native           |                       -0.1 [-3.7, +5.4] |       1569 KiB |    -0.1% |
| v2               |                       -0.4 [-5.6, +2.2] |       1568 KiB |    +0.1% |
| v3               |                       -1.5 [-8.0, +1.6] |       1568 KiB |    +0.0% |
| fat_cgu1_native  |                       +3.5 [+1.9, +5.7] |       1225 KiB |    -0.2% |
| fat_cgu1_v2      |                       +4.1 [+2.9, +6.9] |       1225 KiB |    -0.3% |
| fat_cgu1_v3      |                       +6.7 [+2.1, +9.8] |       1224 KiB |    -0.3% |
| thin_cgu1_native |                       +4.6 [+3.1, +9.9] |       1296 KiB |    -0.2% |
| fat_cgu1_abort   |                       +6.5 [+2.9, +8.8] |       1074 KiB |    -0.4% |
| fat_cgu1_tune    |                       +5.2 [+3.7, +9.3] |       1230 KiB |    -0.1% |

No CPU option separates from its LTO-only counterpart beyond the intervals. A wheel compiled for a newer instruction set would also fail with an illegal instruction on older user CPUs, which a published wheel cannot rule out.

## PGO and BOLT

Eleven rounds, built with fat LTO and one unit. `pgo_e2e` was trained on the guard workload and four `benchmarks.public_shared_cache` cells against MongoDB, so the micro workloads are its held-out check; `pgo_self` was trained on the micro workloads, which makes them in-sample. `bolt` post-processes the LTO build with LLVM BOLT 22.1.8 (Fedora's `llvm-bolt` package, extracted without installing) using an instrumentation profile of the same end-to-end workloads, and `pgo_bolt` does the same for `pgo_e2e`. The `fat_cgu1_reloc` row is the LTO build linked with `--emit-relocs`, which BOLT requires.

| Configuration  | Geometric mean change, % [95% interval] | Extension size | Peak RSS |
| -------------- | --------------------------------------: | -------------: | -------: |
| control        |                       +0.3 [-0.2, +6.8] |       1569 KiB |    +0.0% |
| fat_cgu1       |                       +4.2 [+3.9, +7.5] |       1224 KiB |    -0.1% |
| thin_cgu1      |                       +4.6 [+4.1, +5.3] |       1294 KiB |    -0.0% |
| pgo_e2e        |                    +16.1 [+15.7, +16.5] |       1322 KiB |    -0.1% |
| pgo_self       |                    +19.7 [+19.6, +19.8] |       1264 KiB |    -0.4% |
| bolt           |                       +4.8 [+4.3, +8.7] |       6652 KiB |    -0.2% |
| pgo_bolt       |                    +16.2 [+16.0, +21.8] |       6614 KiB |    +0.1% |
| fat_cgu1_reloc |                       +4.8 [+4.5, +6.1] |       1736 KiB |    -0.1% |

BOLT adds nothing measurable to either build and needs an additional LLVM distribution, relocation-preserving links and a second instrumented training run. PGO trained on end-to-end workloads gains 16% on the held-out micro workloads, so it is retained; the next two sections measure the shipping pipeline.

## Final comparison with `main`

Fifteen rounds of `main`'s wheel against the wheel built from this branch. `lto_wheel` is the same Maturin/Zig build with only the Cargo profile, so it separates the two retained changes. Extension sizes are 1,131 KiB for `main`, 978 KiB for `lto_wheel` and 1,072 KiB for the shipped wheel.

| Workload                     |              LTO only |      Shipped (LTO + PGO) |           A/A control |
| ---------------------------- | --------------------: | -----------------------: | --------------------: |
| `admit_churn_medium`         |     +5.6 [+4.7, +6.2] |     +28.4 [+27.5, +28.9] |     +0.1 [-0.5, +0.4] |
| `admit_churn_small`          |     +4.6 [+3.8, +5.3] |     +28.4 [+27.3, +29.0] |     +0.2 [-0.8, +0.7] |
| `capture_array`              |     +8.0 [+7.5, +8.2] |     +12.4 [+11.9, +12.7] |     +0.4 [+0.3, +1.0] |
| `echo_roundtrip`             |     +1.1 [+0.4, +2.0] |        +3.8 [+3.5, +4.2] |     -0.5 [-1.2, -0.1] |
| `facade_find_miss`           |     +2.4 [+1.1, +3.0] |     +23.8 [+23.2, +24.0] |     -0.3 [-0.5, +0.1] |
| `facade_hit`                 |     +2.0 [+1.7, +2.6] |       +9.4 [+8.5, +10.3] |     -0.3 [-0.9, +0.0] |
| `facade_invalidation`        |     +5.1 [+3.3, +6.0] |     +12.5 [+12.1, +12.8] |     -0.1 [-0.8, +0.2] |
| `find_exact_hit`             |     -0.6 [-1.3, +0.8] |     +19.2 [+18.4, +20.5] |     -0.9 [-1.8, -0.0] |
| `find_subsumed_hit`          |     +4.4 [+4.1, +4.9] |     +28.6 [+28.2, +29.0] |     +0.0 [-0.8, +0.5] |
| `identity_hit_decoded_small` |     +0.1 [-0.4, +1.0] |        +5.9 [+5.6, +6.3] |     -0.6 [-1.0, -0.2] |
| `identity_hit_medium`        |     +3.5 [+3.3, +4.1] |     +17.1 [+15.9, +17.7] |     -0.5 [-0.7, -0.0] |
| `identity_hit_small`         |     +4.1 [+4.0, +4.7] |     +17.4 [+17.0, +17.8] |     -0.5 [-0.9, +0.3] |
| `identity_miss`              |     +1.4 [+0.6, +2.8] |     +14.1 [+13.9, +14.4] |     +0.3 [-0.6, +0.9] |
| `key_preparation_large`      |     +7.0 [+6.8, +7.5] |     +12.1 [+11.4, +12.7] |     +0.6 [-0.0, +1.0] |
| `key_preparation_small`      |     +3.4 [+2.4, +4.1] |      +10.0 [+9.0, +10.2] |     -0.3 [-1.1, +0.1] |
| `namespace_hit`              |     +6.9 [+6.3, +7.8] |     +25.9 [+25.8, +26.1] |     -0.9 [-1.6, +0.1] |
| `namespace_lifecycle`        |     +3.8 [+3.3, +4.2] |      +10.6 [+9.9, +11.1] |     +0.8 [+0.2, +1.4] |
| `owner_admission`            |     +8.0 [+6.8, +9.6] |     +27.8 [+27.3, +29.3] |     +0.7 [-0.8, +1.6] |
| `shared_hit_medium`          |     +5.2 [+4.4, +5.9] |     +27.5 [+27.4, +27.8] |     +0.5 [-0.1, +0.7] |
| `shared_hit_small`           |     +3.7 [+2.8, +4.1] |     +37.7 [+36.4, +38.3] |     +0.4 [-1.1, +1.7] |
| `shared_miss`                |     +8.2 [+7.4, +8.9] |     +26.0 [+25.6, +26.6] |     +0.5 [+0.4, +1.6] |
| `shared_publish_cycle`       |     +7.0 [+5.8, +7.3] |     +23.7 [+22.7, +24.2] |     +0.9 [-0.6, +3.4] |
| `snapshot`                   |     +2.3 [+1.0, +3.0] |        +2.7 [+2.2, +3.5] |     +1.5 [-0.5, +2.4] |
| `wire_keys`                  |     +2.2 [+1.8, +2.7] |        +9.2 [+8.9, +9.8] |     -0.3 [-0.9, +0.2] |
| `write_invalidation`         |     +2.1 [+1.5, +2.7] |     +15.4 [+15.0, +16.1] |     +0.0 [-0.6, +1.1] |
| **geometric mean**           | **+4.0 [+3.8, +4.2]** | **+18.4 [+18.4, +18.6]** | **-0.1 [-0.5, +0.3]** |

`snapshot` and `namespace_lifecycle` are never trained, and neither regresses: a function absent from the profile is optimized for size, and these two still improved.

### End to end

Nine rounds of the guard workload.

| Workload                |              LTO only |   Shipped (LTO + PGO) |           A/A control |
| ----------------------- | --------------------: | --------------------: | --------------------: |
| `async_hit/medium`      |     -0.8 [-1.4, +0.5] |     +4.9 [+3.0, +5.7] |     -0.5 [-2.2, +0.2] |
| `async_hit/small`       |     +0.5 [-0.2, +2.5] |     +5.6 [+4.2, +7.4] |     +0.3 [-1.6, +2.5] |
| `find_admission/medium` |     +4.1 [-1.7, +8.4] |     +1.7 [-3.9, +9.4] |    +1.7 [-11.0, +4.1] |
| `find_admission/small`  |     +0.1 [-5.1, +4.2] |     +0.0 [-6.1, +7.4] |     +1.7 [-4.4, +5.7] |
| `invalidation/medium`   |     +3.4 [+2.8, +4.3] |     +9.3 [+9.0, +9.6] |     -0.2 [-0.7, +0.8] |
| `invalidation/small`    |     +3.4 [+1.2, +5.3] |     +8.5 [+8.3, +9.4] |     +0.0 [-0.3, +1.2] |
| `sync_hit/medium`       |     +0.1 [-1.2, +1.1] |     +4.7 [+1.4, +5.5] |     -1.2 [-2.1, -0.4] |
| `sync_hit/small`        |     +1.8 [+0.1, +4.0] |     +5.9 [+4.9, +7.7] |     +0.2 [-2.0, +2.5] |
| **geometric mean**      | **+1.5 [+0.6, +2.9]** | **+5.1 [+4.3, +7.3]** | **+0.1 [-1.7, +1.2]** |

`find_admission` is dominated by MongoDB round trips, so its intervals contain zero for every build. A training set limited to the entry points in isolation gave 3.0% [1.7, 5.0] end to end; adding the facade's own call sequences (`is_database_available`, `try_current_epoch`, decoded lookups, change-event routing) raised it to the figure above, which is why the training script includes them.

## Pipeline findings

- The profile is keyed by function names, which embed crate hashes. A hand-written pipeline that built the instrumented wheel with the host linker left 869 functions of the Zig wheel without profile data, and the gain was 5% instead of 18%; cargo-zigbuild enables Cargo's unstable `target-applies-to-host` mode, which is the likely cause of the different hashes. Maturin's own `--pgo` builds both passes with Zig, so the release build uses it: its wheel was as fast as the corrected hand-written pipeline (+23.0% against +21.8% geometric mean on eight workloads, seven rounds), and it fails without writing a wheel when `llvm-profdata` is missing or the training command fails, which were both tried.
- Zig rejects rustc's separate `-u __llvm_profile_runtime` operand, so `scripts/zig-linker.sh` joins it into `-Wl,-u,…`.
- The measurements ran with Maturin 1.15.0. The shipped build needs 1.16.0, the first release that honors `pgo-dependency-group`, and its wheel measured the same (+20.8% against +21.1% geometric mean on nine workloads, seven rounds). uv adds the default `dev` group to the group Maturin exports, so `just build` sets `UV_NO_DEFAULT_GROUPS=1`; without it the training environment held 75 contributor packages instead of the wheel's three dependencies.
- `just build` takes 37.9 s with a 380 MiB peak, against 8.5 s and 404 MiB for `main`'s source distribution and wheel, because it compiles the extension three times and runs the training. The shipped extension is 5% smaller than `main`'s.

## Tests and validation

- `just tests_and_coverage` passes on the branch with 100% coverage.
- The existing selection (4,554 passed, 1 skipped on both revisions) took 339.5 s and 337.4 s on `main` and 338.1 s and 335.3 s on the branch, run alternately with the editable development build; the difference is within the run-to-run spread. The 26 added tests (`tests/test_pgo_training.py`) take 0.8 s.
- The Loom models (`just rust-models`) ran their tests in 42.2 s against 45.5 s on `main`; compilation plus tests took 58.8 s against 52.3 s.
- Import time of the extension stayed at 155 ms ± 1 ms, and peak RSS of the workloads changed by −0.2% for the shipped wheel.
- A build without `llvm-profdata` fails with the missing-component message and writes no wheel.

## Reproduction

Run from the repository root of this branch on the machine to measure; the commands derive the target triple from the host, so they apply to x86-64 and ARM64 alike (`x86-64-v2` and `x86-64-v3` exist only on x86-64). Raw outputs stay under `/tmp/agents/rust-profile/` and are not committed. Revision `46edbdac` is the last one before this change; a worktree of it supplies the unmodified `Cargo.toml` as the baseline.

```bash
root="$PWD"
scratch=/tmp/agents/rust-profile
host="$(rustc -vV | sed -n 's/^host: //p')"
export PYO3_PYTHON="$root/.venv/bin/python"
git worktree add --detach "$scratch/main" 46edbdac

overlay() {  # overlay <label> <extension>: the package with another extension
  mkdir -p "$scratch/overlay/$1/client_query_cache"
  rsync -a --delete --exclude __pycache__ --exclude '*.so' src/client_query_cache/ "$scratch/overlay/$1/client_query_cache/"
  cp "$2" "$scratch/overlay/$1/client_query_cache/_shared_index.abi3.so"
}
build() {  # build <label> <worktree> [ENV=value ...]: a Cargo build with overrides
  label="$1"; worktree="$2"; shift 2
  CARGO_TARGET_DIR="$scratch/target/$label" env CARGO_BUILD_TARGET="$host" "$@" \
    cargo build --release --locked --manifest-path "$worktree/native/shared-index/Cargo.toml" --features python
  overlay "$label" "$scratch/target/$label/$host/release/lib_shared_index.so"
}
zig_wheel() {  # zig_wheel <worktree> <output-directory>: a Maturin/Zig wheel without profile guidance
  (cd "$1" && CARGO_ZIGBUILD_PYTHON_PATH="$PWD/scripts/zig-linker.sh" "$root/.venv/bin/maturin" build --release --zig --compatibility manylinux_2_28 --locked --out "$2")
}
wheel_overlay() {  # wheel_overlay <label> <wheel>
  mkdir -p "$scratch/wheels/$1"
  unzip -q -o "$2" -d "$scratch/wheels/$1"
  overlay "$1" "$scratch/wheels/$1/client_query_cache/_shared_index.abi3.so"
}
```

Cargo profile, CPU target and panic strategy against the unmodified baseline, with an A/A control (a copy of the baseline binary):

```bash
build baseline "$scratch/main"
build fat_cgu1 "$scratch/main" CARGO_PROFILE_RELEASE_LTO=fat CARGO_PROFILE_RELEASE_CODEGEN_UNITS=1
build native "$scratch/main" 'RUSTFLAGS=-C target-cpu=native'
build abort "$scratch/main" CARGO_PROFILE_RELEASE_LTO=fat CARGO_PROFILE_RELEASE_CODEGEN_UNITS=1 CARGO_PROFILE_RELEASE_PANIC=abort
cp -a "$scratch/overlay/baseline" "$scratch/overlay/control"
.venv/bin/python -m research.native_build_profile.compare --overlay-root "$scratch/overlay" --baseline baseline --labels control fat_cgu1 native abort --rounds 9 --startup --output "$scratch/matrix.json"
```

The shipped wheels, which separate the two retained changes. `main_wheel` is revision `46edbdac`'s release wheel, `lto_wheel` is this branch's Cargo profile without profile guidance, and `pgo_wheel` is `just build`'s output:

```bash
zig_wheel "$scratch/main" "$scratch/main-wheel"; wheel_overlay main_wheel "$scratch/main-wheel"/*.whl
cp -a "$scratch/overlay/main_wheel" "$scratch/overlay/control_wheel"
zig_wheel "$root" "$scratch/lto-wheel"; wheel_overlay lto_wheel "$scratch/lto-wheel"/*.whl
just build; wheel_overlay pgo_wheel "dist/client_query_cache-$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -1)"-*.whl
.venv/bin/python -m research.native_build_profile.compare --overlay-root "$scratch/overlay" --baseline main_wheel --labels control_wheel lto_wheel pgo_wheel --rounds 15 --startup --output "$scratch/final.json"
cp -a "$scratch/overlay/lto_wheel" "$scratch/overlay/control_lto_wheel"
.venv/bin/python -m research.native_build_profile.compare --overlay-root "$scratch/overlay" --baseline lto_wheel --labels control_lto_wheel pgo_wheel --rounds 15 --output "$scratch/pgo-over-lto.json"
source scripts/testcontainers-bridge.sh
.venv/bin/python -m research.native_build_profile.end_to_end --overlay-root "$scratch/overlay" --baseline main_wheel --labels control_wheel lto_wheel pgo_wheel --rounds 9 --repeats 3 --output "$scratch/e2e.json"
.venv/bin/python -m research.native_build_profile.end_to_end --overlay-root "$scratch/overlay" --baseline lto_wheel --labels control_lto_wheel pgo_wheel --rounds 9 --repeats 3 --output "$scratch/e2e-pgo-over-lto.json"
```

The last `compare.py` and `end_to_end.py` runs measure profile guidance alone against the LTO-only wheel, with an A/A copy of that wheel as their noise control. Passing `--workloads` limits a run to named workloads, and `--cpu` picks the pinned core.

The PGO and BOLT variants of the Cargo builds:

```bash
lto=(CARGO_PROFILE_RELEASE_LTO=fat CARGO_PROFILE_RELEASE_CODEGEN_UNITS=1)
build pgo_gen "$scratch/main" "${lto[@]}" "RUSTFLAGS=-C profile-generate=$scratch/raw"
LLVM_PROFILE_FILE="$scratch/raw/%m-%p.profraw" PYTHONPATH="$scratch/overlay/pgo_gen:$root" .venv/bin/python scripts/pgo_training.py
"$(rustc --print sysroot)/lib/rustlib/$host/bin/llvm-profdata" merge -o "$scratch/pgo.profdata" "$scratch"/raw/*.profraw
build pgo "$scratch/main" "${lto[@]}" "RUSTFLAGS=-C profile-use=$scratch/pgo.profdata"
```

BOLT (x86-64 only here): build with `"RUSTFLAGS=-C link-arg=-Wl,--emit-relocs"`, run `llvm-bolt in.so -o out.so -instrument --runtime-instrumentation-lib=libbolt_rt_instr.a --instrumentation-file=prof --instrumentation-file-append-pid`, train the output, run `merge-fdata prof.* -o merged.fdata`, then `llvm-bolt in.so -o final.so -data=merged.fdata -reorder-blocks=ext-tsp -reorder-functions=cdsort -split-functions -split-all-cold -split-eh`.

## Limitations

- One x86-64 host with frequency scaling and neighbouring containers; the intervals reflect that noise but not other machines.
- The ARM64 wheels follow the same pipeline and are verified by the ARM64 CI job, but their gain was not measured: [#401](https://github.com/alessio-locatelli/client-query-cache/issues/401) tracks it. Run the shipped-wheel comparisons of the reproduction section on an ARM64 host: the A/A controls give the noise, `lto_wheel` against `main_wheel` the effect of the Cargo profile, and `pgo_wheel` against `lto_wheel`, in the native workloads and end to end, the effect of profile guidance alone.
- The native workloads model the facade's call sequences rather than observe them; a native entry point that joins the hot path must be added to `scripts/pgo_training.py`.
- The end-to-end gain is bounded by the Python facade and PyMongo, which this change leaves untouched.
