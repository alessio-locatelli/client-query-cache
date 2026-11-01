# Native internals acquisition plan

This file registers the builds, commands, and resource scope for the [migrate-remaining-hotpaths-to-rust](../../openspec/changes/migrate-remaining-hotpaths-to-rust/design.md) change. Workload selection, budgets, and decision rules belong to design decision D6; this file does not restate them. Observations and dispositions belong to [results.md](results.md).

## Builds

| Label       | Source                                                                                                            | Role                                                  | Wheel SHA-256                                                      | Extension SHA-256                                                  |
| ----------- | ----------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------------ |
| M           | [c931b679](https://github.com/alessio-locatelli/client-query-cache/tree/c931b679ce612dde46246329ea430d4d847c396f) | Frozen main (0.10.0)                                  | `45a63471198c98781ffd7bea5cc7c5262665cd1d9ee407a2b8434fcbe345c9a0` | `4ef9fa159c60547a476e9fe15e430dfe7e8590a237108c66fb4aec4feeb5442b` |
| capture     | [e4a4f0de](https://github.com/alessio-locatelli/client-query-cache/tree/e4a4f0deccc09845ac3388e7bc9a074ae9577878) | Encoded capture (D2); predecessor M                   | `449554b295516791183f57d7555c085f26648dde1a40fceac7d9cdd7e46ebf61` | `e78c1b48dbc2e0b499de66af5a369f8a2dd5ba53b5fa60b0fd403564e7faef66` |
| preparation | [9b15985b](https://github.com/alessio-locatelli/client-query-cache/tree/9b15985b995790aad30a267f6f8a03514314a21f) | Native key preparation (D3); predecessor capture      | `db51c069f9db1ca678b27ad6653a9a619d7345687c9656c7dcf78faab4613511` | `8bf0cc3d5c8b02ed0d1c147dcf5a9dfe555c2dd24f8fe38f8a0e9ee35866c56c` |
| owner       | [29106b20](https://github.com/alessio-locatelli/client-query-cache/tree/29106b20d64418de6b4267e86029c1858419f0e4) | Native shared ownership (D4); predecessor preparation | `adec5e74e1671ffb24b75916948472cfe18c2ed9377f2db40438f74af32411e5` | `9c6a29c88faf13724aa2d09c5559545406975c9305763981a7e52498c4b7ddc9` |
| dispatch    | [bdf96534](https://github.com/alessio-locatelli/client-query-cache/tree/bdf965340f191b16a8115171fb4fb8a13a183900) | Facade dispatch (D5); predecessor owner               | `a23d14a12c62705c33e956d3e45d0df02c43fd961fdbc4a2577ee9198c258991` | `9c6a29c88faf13724aa2d09c5559545406975c9305763981a7e52498c4b7ddc9` |
| F           | [c02c7f27](https://github.com/alessio-locatelli/client-query-cache/tree/c02c7f27e76ee7bd100ad2aff932355472c58459) | Final retained tree; combined campaign against M      | `3783da9be08d9e58ff24775d33900575868bc76f95eced9d4f9a6e3f5ef741b6` | `3e4f79cb836e9acc123bcf8ee84b0dace1aa105fbe7a08077d33256ddf9d6364` |

The candidate wheels were built without a fixed archive timestamp and are not byte-reproducible; their timing used the registered digests. M and F are built with `SOURCE_DATE_EPOCH` set to the commit time, which makes the wheel reproducible. M's rebuilt wheel has the same extension digest as the M wheel used for candidate timing. Each candidate's predecessor is the latest retained label; M is the predecessor of the first candidate. A candidate row and its `native-internals` entry in `research/native_local_integration/registration.py` are added before that candidate's timing. Labels identify revisions; every label in this registration uses the native `LocalCacheCore`.

All environments use CPython 3.14.7 on Linux 7.2.13 x86-64, glibc 2.43. M and the candidate labels use PyMongo 4.18.3 and `uv.lock` SHA-256 `ceccf51b5271a062bf2add40a3c3b03f87b9aa572050ccca1b756d956bc26337`. The branch was then rebased onto main `f7abe5ea`, which updates PyMongo and the development packages, so F uses PyMongo 4.19.0 and `uv.lock` SHA-256 `73a40da6d6ebc87bf7ccafdb616ed9899f96d6aa9faceb6905aee4d076682a96`. The combined campaign keeps M at `c931b679`, so its M→F differences include that dependency update. The candidate and harness commits recorded before the rebase are local pre-rebase commits; the rebased branch carries the same changes under new hashes. MongoDB is `mongo:9.0.4@sha256:dc28ed5a9d0fc616903c3f463bb1e53b92b49f441721b91926e87d90bf957ce8`.

Build every label from its own detached checkout and install the release wheel into that checkout's environment:

```bash
git worktree add --detach /tmp/agents/native-internals/<label> <commit>
cd /tmp/agents/native-internals/<label>
uv sync --locked --no-install-project --group docs --quiet
export SOURCE_DATE_EPOCH="$(git log -1 --format=%ct)"
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
<installed-python> -m research.native_local_integration.acquire --registration native-internals --label <label> --block <0-2> --wheel <absolute-wheel> --existing-nodes /tmp/agents/native-internals/existing-nodes.txt --components candidate --candidate <capture|preparation|owner|dispatch> --profile --output /tmp/agents/native-internals/bench-<candidate>/b<block>-<label>
```

`--profile` adds one bounded profiled window per target cell and model after its timed window. Profiled windows never enter timing comparisons. Before a candidate's timing, record its baseline-only calibration below and adjust the registered sample counts within D6's ceilings.

**Combined campaign.** Use the existing campaign once against M with the final label F, in M/F, F/M, M/F, F/M, M/F order:

```bash
<installed-python> -m research.native_local_integration.acquire --registration native-internals --label <M-or-F> --block <0-4> --wheel <absolute-wheel> --existing-nodes /tmp/agents/native-internals/existing-nodes.txt --components public memory contention --output <new-absolute-output-directory>
<installed-python> -m research.native_local_integration.acquire --registration native-internals --label <M-or-F> --block 5 --wheel <absolute-wheel> --existing-nodes /tmp/agents/native-internals/existing-nodes.txt --test-checkout <matching-checkout> --components tests --output <new-absolute-output-directory>
```

Block 5 runs M, then F with `--added-nodes /tmp/agents/native-internals/added-nodes.txt`. Before it, copy each wheel's native extension into its checkout's `src/client_query_cache`; the test child imports that source package, and `acquire.py` rejects a source package that differs from the wheel.

## Process and resource scope

Public cells use the collector's spawned worker processes (four unless a registered cell states otherwise), one serial caller per worker, majority reads, and no writer. MongoDB runs in a disposable container limited to two CPUs and 1 GiB; its CPU is reported separately and never enters per-read library CPU. Shared cells add the spawned owner, whose CPU comes from its POSIX process clock in the supervisor. Group CPU is worker plus owner plus read supervision. Seeding, collector startup, profiled windows, MongoDB, builds, and test processes are excluded from per-read CPU. Memory observations are per-process PSS/RSS from the collector checkpoints; tracemalloc is not a total-memory measure.

## Existing-test selection

Collect the default non-memory selection of each of M and F from its checkout and installed environment:

```bash
uv run --no-sync -- pytest --collect-only -q -n 0 -p no:cacheprovider --log-file=/tmp/agents/native-internals/collection-<label>.log | rg '^tests/.*::' | LC_ALL=C sort > /tmp/agents/native-internals/nodes-<label>.txt
LC_ALL=C comm -12 /tmp/agents/native-internals/nodes-M.txt /tmp/agents/native-internals/nodes-F.txt > /tmp/agents/native-internals/existing-nodes.txt
LC_ALL=C comm -13 /tmp/agents/native-internals/nodes-M.txt /tmp/agents/native-internals/nodes-F.txt > /tmp/agents/native-internals/added-nodes.txt
```

M's list has 4,445 node IDs (SHA-256 `0932ab7d5cd03042c753506af599a7045efe8b9387769b0cec019643f8270ec7`), the selection the candidate benchmarks were registered with; F's has 4,552. The existing selection is the 4,397 node IDs both revisions collect (SHA-256 `027915fc95f2652e9f922d82e7daea1dfa0c4770ae79431551f19e56726c593a`); the other 48 M tests covered the removed Python owner and residency code or were renamed by the native-core parametrization. The 155 added node IDs (SHA-256 `bef04dba1829bf47057970e69001e75cf64e1353d9c6b0c4c3228707b17b1da7`) are timed only on F.

## Calibration

Event-rate calibration applies only if task 5.1 justifies a routing candidate; it is recorded here before that candidate's timing.

Capture: one M-only synchronous target window, including replica-set startup and seeding of 129 groups × 4,000 documents, took 16.9 seconds; the 128 complete reads used 2.35 CPU-seconds. The registered cells keep D6's ceilings.

Preparation: one capture-only synchronous target window, including replica-set startup and seeding, took 13.8 seconds; its 16,384 hot reads used 54 µs of CPU each. The registered cells keep D6's ceilings.

Owner: one preparation-only synchronous target window took 14.4 seconds; its 4,096 drained cold identity reads used 227 µs of group CPU each, 40 µs of it in the owner. The registered cells keep D6's ceilings. Profiled owner windows sample the owner with py-spy 0.4.2, which must be on `PATH`.

Dispatch: one owner-only synchronous target window, including replica-set startup and seeding, took 12.7 seconds; its 8,192 hot `find()` reads of 16 documents used 58 µs of CPU each. The registered cells keep D6's ceilings. Dispatch changes only Python, so its extension matches owner's.
