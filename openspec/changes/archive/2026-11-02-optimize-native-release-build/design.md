# Design

## Context

The extension is built by Maturin through three routes: editable installs and source-distribution installs (both PEP 517), and `just build`, which Maturin runs with Zig to produce the `manylinux_2_28` wheels that `publish.yml` and `release-verification.yml` build natively on x86-64 and ARM64 runners. The crate has no C dependencies, so cross-language LTO does not apply. Measurements, their method and every rejected option live in `reports/rust-build-profile/summary.md`; this file records only the decisions and why the alternatives lost.

## Goals / Non-Goals

**Goals:**

- Faster native entry points and cached reads for every user of the published wheels, with no source change.
- A release pipeline that cannot silently ship an unprofiled or stale-profile wheel.

**Non-Goals:**

- Optimizing for one CPU model, nightly-only compiler flags, or the Python code.
- Making wheels byte-reproducible.

## Decisions

### D1: Fat LTO and one codegen unit in the crate's release profile

The profile is declared in `Cargo.toml`, so all three build routes inherit it and no wrapper has to remember flags.

| Alternative                            | Pros                                      | Cons                                                                         |
| -------------------------------------- | ----------------------------------------- | ---------------------------------------------------------------------------- |
| Fat LTO + one unit (chosen)            | Largest stable gain among profile options | Longer link; smaller parallelism                                             |
| Thin LTO (+ one unit)                  | Faster to build                           | Statistically indistinguishable from fat in the campaign; no reason to trade |
| One unit alone, `opt-level` 2 or `"s"` | Nothing to configure or smaller binary    | No gain (2) or a large regression (`"s"`)                                    |

Unknowns: none; build time and memory were measured and are negligible for this crate.

### D2: Profile recorded at release-build time on the building host

| Alternative                   | Pros                                     | Cons                                                                                                                                                                                                                  |
| ----------------------------- | ---------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Record at build time (chosen) | Always matches source, toolchain and ISA | Three compilations per wheel; wheels are not byte-reproducible; release jobs need the `llvm-tools` component                                                                                                          |
| Commit a merged profile       | Single compilation; reproducible         | Stale as soon as Rust source or the toolchain changes; a mismatched profile degrades silently or warns per function; ARM64 cannot reuse the x86-64 profile; the file exceeds the repository's 300 KiB large-file hook |
| Skip PGO, keep D1 only        | Simplest                                 | Forgoes the largest measured gain                                                                                                                                                                                     |

Unknowns: ARM64 gain cannot be measured on the development host. The ARM64 job of `test.yml` exercises the pipeline on every pull request that touches native code; the ticket linked from the report tracks measuring its speed-up.

### D3: Release wheels only

Editable installs and sdist consumers keep D1 without a profile: contributors rebuild constantly and sdist consumers may lack the profile tooling or the training environment. A profile applied to a wheel built from another architecture or revision would be silently wrong, so none is shared.

### D4: Training is a MongoDB-free script over the native entry points

| Alternative                        | Pros                                         | Cons                                                                           |
| ---------------------------------- | -------------------------------------------- | ------------------------------------------------------------------------------ |
| Native-entry-point script (chosen) | Runs in the release job; deterministic; fast | Models the facade's call sequence instead of observing it                      |
| End-to-end workload on MongoDB     | Closest to production                        | Needs a container runtime and replica set in the release job; slow             |
| The pytest suite                   | Covers every function                        | Weights error paths like hot paths; a function never run is optimized for size |

The script is also the source of the measurement workloads, so the evaluation reported in the report uses the end-to-end guard workload as its held-out check. A function absent from the profile is optimized for size, so the workload must cover every native entry point the cache hot path reaches; the workload is checked into the repository and a test runs it once, so a signature change fails the suite instead of a release.

### D5: Pipeline mechanics

| Alternative                | Pros                                                                                                                                                                | Cons                                                                                                                                                                          |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Maturin's `--pgo` (chosen) | Maintained tool; builds the instrumented and the final wheel in one build mode; fails on a missing `llvm-profdata`, a failing training command and an empty profile | Configuration is a training command and an empty `pgo` dependency group in `pyproject.toml`; the training environment resolves the wheel's dependencies from the index        |
| A repository script        | Full control over each stage and extra checks                                                                                                                       | Duplicates Maturin. The first version built the instrumented wheel with the host linker, which left 869 functions without profile data and lost most of the gain (see report) |

Unknowns: none. The report shows the built-in wheel is as fast as the scripted one. Maturin 1.16.0 is the first release that honors the dependency group, so the build group's minimum moves to it; uv adds the default `dev` group to the exported group, so the build sets `UV_NO_DEFAULT_GROUPS`. The remaining repository code is the operand join in `scripts/zig-linker.sh`, because Zig reads the separate operand of rustc's `-u` argument as an input file (removal tracked in [#402](https://github.com/alessio-locatelli/client-query-cache/issues/402)).

### D6: Options evaluated and rejected

Post-link layout optimization added nothing beyond PGO, `panic = "abort"` would turn any native panic into a process kill instead of a Python exception, CPU-specific code generation cannot be assumed on user machines and measured no gain, and nightly-only flags would break the stable-toolchain policy in `docs/development/native-quality.md`. Measurements are in the report; none of these needs follow-up.

## Risks / Trade-offs

- [A profile that misses a hot path makes that path slower] → The workload covers all entry points used by cached reads; the report compares held-out and never-trained paths against the unprofiled build.
- [Training environment differs from the build host's Python] → It uses the same interpreter selection and the instrumented wheel built by the same job.
- [Profile tooling breaks on a toolchain bump] → The pipeline fails closed (spec), and Dependabot toolchain updates run the ARM64 and compatibility jobs that build a release wheel.
