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

`python3 -I scripts/installed_build_probe.py audit`, run with either virtual environment's interpreter, prints the installed-package inventory used above.

Tests were run with `python -m pytest tests/synchronous tests/asynchronous --junitxml=...` from each revision's checkout against its own wheel. Deleted tests were not compared.

## Shared-cache warm reads and group PSS

The public benchmark ran against each wheel in its own installation (four workers, isolated replica set, hot window, validated cache outcomes and origin reads, five alternating rounds per build, ten windows per build and API). Every window was valid. Medians, candidate/`main`:

| API   | Median read | Throughput | Worker plus owner PSS | Owner PSS at startup | Startup wall time |
| ----- | ----------- | ---------- | --------------------- | -------------------- | ----------------- |
| sync  | 0.9997      | 1.030      | 0.988                 | 0.987                | 0.975             |
| async | 1.006       | 1.129      | 0.991                 | 0.988                | 0.990             |

Read latency is equal; group PSS is about 1% lower. The throughput gains are within the spread of these short windows and are not claimed.

```bash
source scripts/testcontainers-bridge.sh
PYTHONPATH=. WORKDIR/venv-BUILD/bin/python -m benchmarks.public_shared_cache --validate --samples 1000 --repetitions 2 --workers 4 --paths shared --workloads hot --output OUT.json
```
