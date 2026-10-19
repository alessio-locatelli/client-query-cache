# Read discriminator reuse measurements

## Result

Across seven alternating rounds, median exact-hit CPU fell 11.7% for sync find,
8.8% for async find, 12.5% for sync aggregation, and 12.4% for async aggregation.
The baseline and implementation interquartile intervals do not overlap for any
of these four cases. Full ranges overlap for three cases, and individual paired
rounds sometimes regress; these measurements establish a median improvement on
this workload, not an improvement on every execution.

The raw-root regression observes one preparation per execution through lookup,
complete admission, and find source creation. Restoring the discarded precheck
made all 12 exact-hit/complete-miss/scalar traversal assertions fail. Separate
profiles confirm reduced recursive canonicalization work. Native result-command
counts are unchanged. These results satisfy the per-hit CPU acceptance criterion
for [issue #248](https://github.com/alessio-locatelli/client-query-cache/issues/248).

## Revisions and environment

- Baseline: `d74e67041c26718ec32c8e44d61e811ac5096700`.
- Reproducible implementation: `8d0a35e6f327cc710f131c746908a2ecd90c308b`.
- Measured implementation snapshot: `a24dfd8adf7a505cdcd23342a4fc642c5d835aaa`.
  Its `src/` tree equals the implementation commit's tree, `9798b05cd0e08e3e7006051b40d679bf5bfeaf92`.
  Each measurement worktree's `src/` matched its own checked-out revision before
  and after timing; implementation source was never overlaid onto the baseline.
- CPython 3.14.7, PyMongo 4.18.2 in both worktree environments; MongoDB 8.0.4
  (`mongo:8.0.4-noble`) on one disposable replica-set server for all 14 runs.
- Fedora Toolbx, Linux 7.2.9-200.fc44.x86_64, glibc 2.43; AMD Ryzen 3 210 with
  Radeon 740M Graphics, eight logical CPUs. CPU frequency was not pinned.
- Each case used the same 40 deterministic documents with empty payloads,
  `code="C0000001"`, and `state="a"`, sorted by `_id`, returning 20 documents.
  Find used `{"code": "C0000001", "state": {"$in": ["a", "b", "c"]}}`;
  aggregation used the equivalent `$match`, `$sort`, and `$limit` pipeline.

Metadata, streams, seeded-write processing, and initial admission were warmed
outside timing. Every cold sample cleared the namespace before its timer.
Compatible find hits used a resident limit-100 source containing 40 documents.
There were 5,000 exact or compatible hits and 100 complete cold reads per case
per round. `process_time()` and `perf_counter()` measured CPU and wall time
separately around complete cursor construction and materialization; result
assertions, clearing, and fixture setup were outside the timer. Process CPU
includes the process's background stream threads and excludes MongoDB CPU.
Profiling ran separately after timing, with 500 exact hits; allocation tracing
was disabled during all timed sections.

An initial seven-round trial overlapped coverage validation and was excluded
because its CPU and wall times were visibly unstable. The retained seven rounds
ran after validation stopped. No retained sample or round was discarded.
Implementation round 4 regressed in three of four paired exact-hit cases, and async find in
round 7 was also slower than its paired baseline. The table and ranges retain
these observations. Investigation used the full paired results, interquartile
intervals, and separate profiles rather than treating the outliers as absent.

## CPU and wall time

Each cell below is baseline / implementation CPU microseconds per read.
Odd rounds ran baseline first; even rounds ran implementation first.

| API / method / phase  | Round 1         | Round 2         | Round 3         | Round 4         | Round 5         | Round 6          | Round 7         |
| --------------------- | --------------- | --------------- | --------------- | --------------- | --------------- | ---------------- | --------------- |
| sync/find/exact       | 65.51 / 54.69   | 65.43 / 55.64   | 62.23 / 57.77   | 63.12 / 62.08   | 64.18 / 55.49   | 68.17 / 58.93    | 65.28 / 57.67   |
| sync/find/cold        | 481.50 / 440.31 | 476.33 / 501.72 | 493.66 / 484.98 | 450.21 / 547.41 | 556.27 / 458.54 | 512.55 / 452.19  | 558.59 / 453.85 |
| sync/find/compatible  | 82.69 / 69.42   | 75.73 / 71.73   | 77.01 / 67.04   | 76.73 / 78.22   | 76.14 / 69.12   | 77.78 / 71.74    | 82.12 / 71.01   |
| sync/aggregate/exact  | 59.64 / 49.76   | 59.33 / 50.16   | 60.20 / 52.64   | 62.30 / 73.39   | 59.99 / 52.82   | 61.58 / 50.98    | 61.08 / 56.17   |
| sync/aggregate/cold   | 482.70 / 389.97 | 514.27 / 437.05 | 475.05 / 420.53 | 472.95 / 420.45 | 450.51 / 475.59 | 501.47 / 554.96  | 510.20 / 452.57 |
| async/find/exact      | 65.48 / 55.83   | 67.62 / 60.40   | 66.06 / 57.30   | 65.56 / 68.72   | 68.84 / 57.36   | 67.16 / 60.84    | 66.23 / 67.03   |
| async/find/cold       | 823.44 / 615.38 | 672.93 / 679.54 | 601.96 / 625.75 | 606.81 / 653.70 | 723.97 / 615.20 | 666.66 / 558.44  | 610.44 / 704.00 |
| async/find/compatible | 79.63 / 70.08   | 78.66 / 73.66   | 78.73 / 68.91   | 79.42 / 83.17   | 81.06 / 71.81   | 88.28 / 70.36    | 80.00 / 76.78   |
| async/aggregate/exact | 60.72 / 54.53   | 60.85 / 51.92   | 60.60 / 54.05   | 61.93 / 73.66   | 63.16 / 50.66   | 72.46 / 51.25    | 61.41 / 53.80   |
| async/aggregate/cold  | 624.36 / 677.07 | 636.66 / 545.64 | 662.23 / 699.17 | 617.58 / 826.56 | 657.53 / 599.55 | 1268.15 / 618.20 | 581.30 / 731.40 |

CPU ranges include all seven rounds. Wall values are medians in microseconds.
CPU change compares the two CPU medians.

| API / method / phase  | Baseline CPU median [range] | Implementation CPU median [range] | CPU change | Wall baseline / implementation |
| --------------------- | --------------------------- | --------------------------------- | ---------- | ------------------------------ |
| sync/find/exact       | 65.28 [62.23, 68.17]        | 57.67 [54.69, 62.08]              | -11.7%     | 64.77 / 57.24                  |
| sync/find/cold        | 493.66 [450.21, 558.59]     | 458.54 [440.31, 547.41]           | -7.1%      | 768.54 / 742.67                |
| sync/find/compatible  | 77.01 [75.73, 82.69]        | 71.01 [67.04, 78.22]              | -7.8%      | 76.52 / 70.75                  |
| sync/aggregate/exact  | 60.20 [59.33, 62.30]        | 52.64 [49.76, 73.39]              | -12.5%     | 59.66 / 52.17                  |
| sync/aggregate/cold   | 482.70 [450.51, 514.27]     | 437.05 [389.97, 554.96]           | -9.5%      | 783.20 / 750.97                |
| async/find/exact      | 66.23 [65.48, 68.84]        | 60.40 [55.83, 68.72]              | -8.8%      | 65.66 / 59.87                  |
| async/find/cold       | 666.66 [601.96, 823.44]     | 625.75 [558.44, 704.00]           | -6.1%      | 919.61 / 880.38                |
| async/find/compatible | 79.63 [78.66, 88.28]        | 71.81 [68.91, 83.17]              | -9.8%      | 79.14 / 71.32                  |
| async/aggregate/exact | 61.41 [60.60, 72.46]        | 53.80 [50.66, 73.66]              | -12.4%     | 60.84 / 53.23                  |
| async/aggregate/cold  | 636.66 [581.30, 1268.15]    | 677.07 [545.64, 826.56]           | +6.3%      | 893.49 / 1027.68               |

| Exact-hit case        | CPU interquartile interval: baseline / implementation | Faster paired rounds |
| --------------------- | ----------------------------------------------------- | -------------------- |
| sync/find/exact       | [63.65, 65.47] / [55.56, 58.35]                       | 7/7                  |
| sync/aggregate/exact  | [59.81, 61.33] / [50.57, 54.50]                       | 6/7                  |
| async/find/exact      | [65.81, 67.39] / [57.33, 63.94]                       | 5/7                  |
| async/aggregate/exact | [60.78, 62.54] / [51.59, 54.29]                       | 6/7                  |

The median exact-hit savings exceed each baseline's interquartile spread, and
both interquartile intervals separate. Full observed variation is larger than
the savings in three cases, so the evidence supports a typical CPU improvement,
with the stated uncertainty. Compatible find medians improved 7.8% and 9.8%.
Cold-path ranges overlap substantially: async aggregation's median CPU increased
6.3%, while the other cold medians fell 6.1–9.5%. Cold network execution and
background work dominate this small sample; no cold-path speedup is claimed.

Every exact and compatible phase recorded 5,000 hits, zero misses, and zero
`find`, `aggregate`, `getMore`, or `killCursors` commands. Every cold phase
recorded 100 misses and exactly 100 corresponding result commands, with no
`getMore` or `killCursors`. The assertions passed for both revisions in every
round. Metadata commands are outside these result-command counters and were
warmed before timing.

## Profile evidence

Representative round 3 profiles, 500 exact hits per row:

| Case            | Total canonicalize calls: baseline / implementation | Cumulative canonicalize seconds: baseline / implementation | Order-sensitive builder calls (both) |
| --------------- | --------------------------------------------------- | ---------------------------------------------------------- | ------------------------------------ |
| sync find       | 28,500 / 16,500                                     | 0.053 / 0.029                                              | 13,500                               |
| async find      | 28,500 / 16,500                                     | 0.052 / 0.029                                              | 13,500                               |
| sync aggregate  | 32,000 / 16,500                                     | 0.053 / 0.028                                              | 16,000                               |
| async aggregate | 32,000 / 16,500                                     | 0.054 / 0.030                                              | 16,000                               |

These totals count recursive calls and canonical passthrough; they are not the
raw-root traversal bound. Find's primitive canonicalize calls rise from 1,500
to 2,000 because it creates constant-size wrappers around the prepared family,
while total recursive work falls. Aggregation primitive calls stay at 1,000.
The unchanged order-sensitive builder takes 0.026–0.034 cumulative seconds in
the implementation profiles, comparable to the remaining canonicalization
cost. BSON decoding takes 0.004–0.005 seconds. The builder, safety checks, and
remaining key operations dominate this small-result workload; eliminating the
builder pass would require a separate design decision.

## Reproduction

Run from the repository checkout, with its development environment available.
Use disposable worktrees; the same test-only overlays are necessary because the
baseline predates the benchmark. All overlay files matched these SHA-256 hashes
in both measurement worktrees:

| Overlay                                       | SHA-256                                                            |
| --------------------------------------------- | ------------------------------------------------------------------ |
| `tests/benchmark/test_cached_read_cursors.py` | `3f6e2d091e8d3188f4192030c579356b0b2339a5cb413dc664dd3101a2836268` |
| `tests/conftest.py`                           | `184527dd443df0026811e5b1568b8912a1fa4babcd42649084ebf2c5e281446e` |
| `tests/cursor_fixtures.py`                    | `74c3e966d46716c56718d994d815bb0062701a15ced31e03651b53137c49cb3f` |
| `tests/cursor_helpers.py`                     | `ba973a793841fc943d86705b03f99c9a39db48e450a5423e4879604699ca2ec2` |
| `tests/stream_helpers.py`                     | `ea92b62061ba39e2d68bf31782a87b82032f0789fba289bf0d4f0ff05dcae3a1` |
| `tests/polling.py`                            | `0732ebb7c47c28bc680667bb22d913962e8ece3095e22c2a780e41f5483751c6` |

```bash
workspace=$(mktemp -d /tmp/agents/read-discriminator-reproduction.XXXXXX)
export READ_DISCRIMINATOR_WORKSPACE="$workspace"
git worktree add --detach "$workspace/baseline" d74e67041c26718ec32c8e44d61e811ac5096700
git worktree add --detach "$workspace/implementation" 8d0a35e6f327cc710f131c746908a2ecd90c308b
uv run --group docs -- python - <<'OVERLAY'
import hashlib
import os
from pathlib import Path
import subprocess

root = Path.cwd()
workspace = Path(os.environ["READ_DISCRIMINATOR_WORKSPACE"])
files = (
    "tests/benchmark/test_cached_read_cursors.py", "tests/conftest.py",
    "tests/cursor_fixtures.py", "tests/cursor_helpers.py",
    "tests/stream_helpers.py", "tests/polling.py",
)
for name in ("baseline", "implementation"):
    target = workspace / name
    for filename in files:
        contents = subprocess.check_output(["git", "show", f"8d0a35e6f327cc710f131c746908a2ecd90c308b:{filename}"], cwd=root)
        (target / filename).write_bytes(contents)
        assert hashlib.sha256((target / filename).read_bytes()).digest() == hashlib.sha256(contents).digest()
    subprocess.run(["git", "diff", "--exit-code", "HEAD", "--", "src/"], cwd=target, check=True)
    with (workspace / f"{name}-collect.log").open("w") as log:
        subprocess.run([
            "just", "pytest", "-n", "0", "-m", "benchmark",
            "tests/benchmark/test_cached_read_cursors.py", "-k", "discriminator",
            "--collect-only", "-q",
        ], cwd=target, check=True, stdout=log, stderr=subprocess.STDOUT)
collections = [
    tuple(line for line in (workspace / f"{name}-collect.log").read_text().splitlines() if line.startswith("tests/benchmark/"))
    for name in ("baseline", "implementation")
]
assert collections[0] == collections[1] and len(collections[0]) == 4
print("\n".join(collections[0]))
OVERLAY
```

Both worktrees collected these four cases:

```text
test_discriminator_measurements[find-sync]
test_discriminator_measurements[find-async]
test_discriminator_measurements[aggregate-sync]
test_discriminator_measurements[aggregate-async]
```

Keep one disposable server alive while alternating the two commands. Run the
controller from the prepared implementation worktree so it uses the pinned
generator fixture for replica-set setup and cleanup. The benchmark's optional
URI override makes both worktrees use that same instance.

```bash
bash <<'RUN'
set -euo pipefail
source scripts/testcontainers-bridge.sh
cd "$READ_DISCRIMINATOR_WORKSPACE/implementation"
uv run --group docs -- python - <<'MEASURE'
import os
from pathlib import Path
import subprocess

from tests.conftest import mongodb_uri

workspace = Path(os.environ["READ_DISCRIMINATOR_WORKSPACE"])
server = mongodb_uri.__wrapped__()
try:
    uri = next(server)
    environment = os.environ.copy()
    environment["READ_DISCRIMINATOR_MONGODB_URI"] = uri
    for round_number in range(1, 8):
        order = ("baseline", "implementation") if round_number % 2 else ("implementation", "baseline")
        for name in order:
            with (workspace / f"{name}-{round_number}.log").open("w") as log:
                subprocess.run([
                    "just", "pytest", "-n", "0", "-m", "benchmark",
                    "tests/benchmark/test_cached_read_cursors.py", "-k", "discriminator", "-s",
                ], cwd=workspace / name, env=environment, check=True,
                   stdout=log, stderr=subprocess.STDOUT)
finally:
    server.close()
for name in ("baseline", "implementation"):
    target = workspace / name
    subprocess.run(["git", "diff", "--exit-code", "HEAD", "--", "src/"], cwd=target, check=True)
    subprocess.run(["git", "status", "--short"], cwd=target, check=True)
MEASURE
RUN
```

Each log emits `DISCRIMINATOR` JSON lines with CPU, wall time, repetition counts,
and result-command counts, followed by separate `DISCRIMINATOR_PROFILE` tables.
Compute per-phase medians and ranges across the seven runs, preserving outliers.
Do not overlap timing with tests, coverage, tracing, or unrelated validation.
Without the override, the ordinary benchmark command uses the disposable server
fixture as usual.

After verifying that the only worktree changes are the intended test overlays,
remove the worktrees with `git worktree remove --force "$workspace/baseline"`
and `git worktree remove --force "$workspace/implementation"`. Raw logs,
measurements, and profiles remain disposable under `/tmp/agents/`; none are
committed.
