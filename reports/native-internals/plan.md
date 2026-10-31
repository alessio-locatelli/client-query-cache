# Native internals acquisition plan

This file registers the builds, commands, and resource scope for the [migrate-remaining-hotpaths-to-rust](../../openspec/changes/migrate-remaining-hotpaths-to-rust/design.md) change. Workload selection, budgets, and decision rules belong to design decision D6; this file does not restate them. Observations and dispositions belong to [results.md](results.md).

## Builds

| Label       | Source                                                                                                            | Role                                             | Wheel SHA-256                                                      | Extension SHA-256                                                  |
| ----------- | ----------------------------------------------------------------------------------------------------------------- | ------------------------------------------------ | ------------------------------------------------------------------ | ------------------------------------------------------------------ |
| M           | [c931b679](https://github.com/alessio-locatelli/client-query-cache/tree/c931b679ce612dde46246329ea430d4d847c396f) | Frozen main (0.10.0)                             | `d133597a0fc6119d2dda266abc3ab8cfc6bb508e2f53585cb8487e300d87b2b8` | `4ef9fa159c60547a476e9fe15e430dfe7e8590a237108c66fb4aec4feeb5442b` |
| capture     | [e4a4f0de](https://github.com/alessio-locatelli/client-query-cache/tree/e4a4f0deccc09845ac3388e7bc9a074ae9577878) | Encoded capture (D2); predecessor M              | `449554b295516791183f57d7555c085f26648dde1a40fceac7d9cdd7e46ebf61` | `e78c1b48dbc2e0b499de66af5a369f8a2dd5ba53b5fa60b0fd403564e7faef66` |
| preparation | [9b15985b](https://github.com/alessio-locatelli/client-query-cache/tree/9b15985b995790aad30a267f6f8a03514314a21f) | Native key preparation (D3); predecessor capture | `db51c069f9db1ca678b27ad6653a9a619d7345687c9656c7dcf78faab4613511` | `8bf0cc3d5c8b02ed0d1c147dcf5a9dfe555c2dd24f8fe38f8a0e9ee35866c56c` |

Each candidate's predecessor is the latest retained label; M is the predecessor of the first candidate. A candidate row and its `native-internals` entry in `research/native_local_integration/registration.py` are added before that candidate's timing. Labels identify revisions; every label in this registration uses the native `LocalCacheCore`.

All environments use CPython 3.14.7, PyMongo 4.18.3 and the same `uv.lock` (SHA-256 `ceccf51b5271a062bf2add40a3c3b03f87b9aa572050ccca1b756d956bc26337`) on Linux 7.2.13 x86-64, glibc 2.43. MongoDB is `mongo:9.0.4@sha256:dc28ed5a9d0fc616903c3f463bb1e53b92b49f441721b91926e87d90bf957ce8`.

Build every label from its own detached checkout and install the release wheel into that checkout's environment:

```bash
git worktree add --detach /tmp/agents/native-internals/<label> <commit>
cd /tmp/agents/native-internals/<label>
uv sync --locked --no-install-project --group docs --quiet
CARGO_ZIGBUILD_PYTHON_PATH="$PWD/scripts/zig-linker.sh" .venv/bin/maturin build --release --zig --compatibility manylinux_2_28 --locked --out /tmp/agents/native-internals/wheels/<label>
uv pip install --python .venv/bin/python --no-deps --reinstall /tmp/agents/native-internals/wheels/<label>/*.whl
.venv/bin/python -I -c 'import hashlib, client_query_cache as c, client_query_cache._shared_index as n; print(c.__file__, n.__file__, hashlib.sha256(open(n.__file__, "rb").read()).hexdigest())'
```

The last command must report paths under that checkout's `.venv/lib/python3.14/site-packages` and the registered extension digest. M reported both. Build and installation time is outside every benchmark deadline. Acquisitions run from the harness checkout, with each label's absolute `.venv/bin/python` and no `src` entry in `PYTHONPATH`; `acquire.py` rejects a wheel whose digest differs from the registration or whose packaged files differ from the installation.

## Commands

Run `source scripts/testcontainers-bridge.sh` once per shell. Raw outputs stay under `/tmp/agents/native-internals/`.

**Development preflight.** One five-minute deadline covers every cell below, including replica-set startup and teardown. Run it after runtime edits and before candidate timing:

```bash
timeout --signal=TERM --kill-after=15s 300s bash -c '
set -euo pipefail
common=(--hot-keys 16 --samples 32 --document-bytes 128 --models sync async --repetitions 1 --validate --diagnostics)
"$0" -m benchmarks.public_shared_cache --method find --result-documents 16 --paths independent shared --workloads cold hot "${common[@]}" --output "$1/find.json"
"$0" -m benchmarks.public_shared_cache --method identity --paths shared --workloads cold "${common[@]}" --output "$1/identity-queue.json"
"$0" -m benchmarks.public_shared_cache --method aggregate --result-documents 128 --paths independent shared --workloads cold "${common[@]/128/1024}" --output "$1/aggregate-large.json"
"$0" -m benchmarks.public_shared_cache --method find_one_in --paths independent shared --workloads cold hot "${common[@]}" --output "$1/find-one-in.json"
' <installed-python> /tmp/agents/native-internals/<step>-preflight
```

The identity cell is the D4 queue check: validated shared cold cells wait for owner processing, reconcile it with worker submissions, and re-read every cold key expecting hits without origin reads. The aggregate cell is the large-result spot check; the `find_one_in` cell is the D3 predicate variant.

**Candidate benchmark.** `research/native_local_integration/acquire.py` defines each candidate's target and control cells in `CANDIDATES`. Run three blocks with predecessor/candidate order P/C, C/P, P/C:

```bash
<installed-python> -m research.native_local_integration.acquire --registration native-internals --label <label> --block <0-2> --wheel <absolute-wheel> --existing-nodes /tmp/agents/native-internals/existing-nodes.txt --components candidate --candidate <capture|preparation|owner> --profile --output /tmp/agents/native-internals/<candidate>/b<block>-<label>
```

`--profile` adds one bounded profiled window per target cell and model after its timed window. Profiled windows never enter timing comparisons. Before a candidate's timing, record its baseline-only calibration below and adjust the registered sample counts within D6's ceilings.

**Combined campaign.** Use the existing campaign once against M with the final label F, in M/F, F/M, M/F, F/M, M/F order:

```bash
<installed-python> -m research.native_local_integration.acquire --registration native-internals --label <M-or-F> --block <0-4> --wheel <absolute-wheel> --existing-nodes /tmp/agents/native-internals/existing-nodes.txt --components public memory contention --output <new-absolute-output-directory>
<installed-python> -m research.native_local_integration.acquire --registration native-internals --label <M-or-F> --block 5 --wheel <absolute-wheel> --existing-nodes /tmp/agents/native-internals/existing-nodes.txt --test-checkout <matching-checkout> --components tests --output <new-absolute-output-directory>
```

## Process and resource scope

Public cells use the collector's spawned worker processes (four unless a registered cell states otherwise), one serial caller per worker, majority reads, and no writer. MongoDB runs in a disposable container limited to two CPUs and 1 GiB; its CPU is reported separately and never enters per-read library CPU. Shared cells add the spawned owner, whose CPU comes from its POSIX process clock in the supervisor. Group CPU is worker plus owner plus read supervision. Seeding, collector startup, profiled windows, MongoDB, builds, and test processes are excluded from per-read CPU. Memory observations are per-process PSS/RSS from the collector checkpoints; tracemalloc is not a total-memory measure.

## Existing-test selection

Collect M's default non-memory selection from its checkout and installed environment:

```bash
uv run --no-sync -- pytest --collect-only -q -n 0 -p no:cacheprovider --log-file=/tmp/agents/native-internals/collection.log | rg '^tests/.*::' | LC_ALL=C sort > /tmp/agents/native-internals/existing-nodes.txt
```

The sorted LF-terminated list has 4,445 node IDs with SHA-256 `0932ab7d5cd03042c753506af599a7045efe8b9387769b0cec019643f8270ec7`. Tests added by this change are timed separately from that selection.

## Calibration

Event-rate calibration applies only if task 5.1 justifies a routing candidate; it is recorded here before that candidate's timing.

Capture: one M-only synchronous target window, including replica-set startup and seeding of 129 groups × 4,000 documents, took 16.9 seconds; the 128 complete reads used 2.35 CPU-seconds. The registered cells keep D6's ceilings.

Preparation: one capture-only synchronous target window, including replica-set startup and seeding, took 13.8 seconds; its 16,384 hot reads used 54 µs of CPU each. The registered cells keep D6's ceilings.
