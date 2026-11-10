# Removing non-production library code: verification summary

Frozen `main` (b12a9f3d) versus candidate commit 8a7c8dfb (`src/`, `native/` and the package metadata are unchanged in later commits), each installed from a PGO-built wheel into its own virtual environment on the same machine. The candidate wheel has 59 files (55 modules, 651,964 bytes, extension 1,104,928 bytes) against 64 files (60 modules, 704,462 bytes, extension 1,175,440 bytes) on `main`. The source distribution has 88 entries: 5 project metadata and toolchain files, 58 under `src/` (the Python package, stubs and `py.typed`), and 25 under `native/shared-index/`, of which 14 are runtime Rust sources, 8 are compile-time-only test files (`tests.rs` and `support_tests.rs`) and 3 are build manifests (`Cargo.toml`, `Cargo.lock`, `deny.toml`); installing it and running the contract suites passes (2790 tests: `tests/core`, `tests/shared_cache`, `tests/synchronous`, `tests/asynchronous`). No retired engine module is loadable, and none of the removed names appear in the installed package.

## Measurements

Ratios are candidate/`main` paired medians with a 95% bootstrap interval; below 1 favors the candidate.

| Measurement                                                                 | Ratio                                           |
| --------------------------------------------------------------------------- | ----------------------------------------------- |
| Import time (40 alternating pairs)                                          | 0.959 [0.933, 0.976]                            |
| Manager construction                                                        | 0.994 [0.979, 1.011]                            |
| Process CPU time                                                            | 0.961 [0.943, 0.980]                            |
| RSS after import / manager / shared                                         | 0.987 / 0.987 / 0.987 (intervals within ±0.002) |
| Cached-read, find-admission, invalidation cases (31 pairs each, 2 profiles) | 0.978 to 1.077, every interval includes 1       |
| Retained synchronous and asynchronous tests (742, identical set)            | 50.4 s against 52.2 s summed test time          |

The widest interval (find-admission, small profile, 0.930 to 1.172) reflects noise; the medium profile of the same case is 1.014 [0.976, 1.079]. No reproducible slowdown was found.

## Reproduction

Create `venv-main` and `venv-cand` inside a work directory `WORKDIR` (installing each revision's wheel, plus `faker` and `psutil`), then run from the repository root:

```bash
PYTHONPATH=. uv run python scripts/installed_build_compare.py startup WORKDIR 40
bash -c 'source scripts/testcontainers-bridge.sh; PYTHONPATH=. uv run python scripts/installed_build_compare.py guard WORKDIR 31'
```

`python3 -I scripts/installed_build_probe.py audit`, run with either virtual environment's interpreter, prints the installed-package inventory used above and exits nonzero when a retired module, export or name is present or a required module fails to import (`main` fails it, the candidate passes).

Tests were run with `python -m pytest tests/synchronous tests/asynchronous --junitxml=...` from each revision's checkout against its own wheel. Deleted tests were not compared.

## Shared-cache warm reads and group PSS

The public benchmark ran against each wheel in its own installation (four workers, isolated replica set, hot window, validated cache outcomes and origin reads). Fifteen rounds alternated which build ran first; each round yields two repetitions per API, so there are 30 paired windows per API. Every window was valid. Candidate/`main` ratio medians with 95% intervals from a bootstrap that resamples whole rounds, because the two repetitions of a round share one benchmark invocation:

| Metric                      | sync                  | async                |
| --------------------------- | --------------------- | -------------------- |
| Median read                 | 0.9996 [0.983, 1.011] | 0.997 [0.955, 1.041] |
| Throughput                  | 0.998 [0.948, 1.075]  | 1.044 [0.985, 1.105] |
| Worker plus owner group PSS | 0.988 [0.988, 0.989]  | 0.990 [0.990, 0.991] |
| Owner PSS at startup        | 0.987 [0.987, 0.988]  | 0.988 [0.987, 0.988] |
| Startup wall time           | 0.977 [0.965, 0.985]  | 0.988 [0.976, 1.000] |

Read latency and throughput show no difference beyond noise (every interval includes 1). Group and owner PSS are about 1% lower with intervals that exclude 1; startup is 1–2% faster, but the asynchronous interval reaches 1.

```bash
source scripts/testcontainers-bridge.sh
for round in $(seq 1 15); do
  for build in $([ $((round % 2)) = 0 ] && echo "cand main" || echo "main cand"); do
    PYTHONPATH=. WORKDIR/venv-$build/bin/python -m benchmarks.public_shared_cache --validate --samples 1000 --repetitions 2 --workers 4 --paths shared --workloads hot --output WORKDIR/raw/shared/$build-$round.json
  done
done
PYTHONPATH=. uv run python scripts/installed_build_compare.py shared WORKDIR 15
```
