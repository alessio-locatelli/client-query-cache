# Shared publication cycle follow-up

On 2026-11-14, the default-allocator timing slowdown reported in
[issue #410](https://github.com/alessio-locatelli/client-query-cache/issues/410)
did not reproduce across three independent release builds per revision and two
acquisitions. Close the investigation without a production change. This result
does not explain or disprove the historical hardware-counter observation.

## Method

The baseline was `4e071dfd5904527545177cd2e6f5bdb78a2239c9`; the candidate was
`94065fbff5439c47268bd38e85b2101c95f9f30f`. Each of the six wheels came from
`just build` in its historical checkout, with a fresh Cargo target directory and
the revision's unchanged PGO training. All six extension SHA-256 hashes differed.
The A/A label was a copy of the first baseline wheel's installed overlay; its
extension hash matched that baseline in every timing child.

The candidate revision's `research.native_build_profile.compare` and training
script drove every overlay. Its `shared_publish_cycle` loops over 1,024 small
entries, calling `store`, `publish`, `unpublish` and `release`. Times below are
per complete cycle, including publication and reclamation. The current training
script has a different workload and was not used.

Each acquisition used seven rounds, shuffling all seven labels within each round.
The order seeds were `20261102` and `20261114`. Each child ran
`shared_hit_medium`, `shared_publish_cycle`, then `capture_array`, with three
warmup batches and 31 measured batches targeting 20 ms each. These are the
issue's two requested comparison controls; they were not investigated further.
Children ran on CPU 2 with address randomization disabled, equal-length overlay
paths and `PYTHONHASHSEED=0`. The harness verified the imported extension path;
the retained local outputs also confirmed a constant extension hash per label.
Its child environment leaves allocator settings at their defaults.

The host was an AMD Ryzen 3 210 with eight logical CPUs, Linux
`7.3.3-300.fc45.x86_64`, glibc 2.44, CPython 3.14.7, PyMongo 4.19.0,
Rust 1.99.1 and maturin 1.16.0. Unlike the historical Intel/glibc 2.43 environment,
this is a new host and allocator version. These measurements test reproducibility
here; they cannot establish what would happen on the original host or recover
its exact PGO layouts. No database or live service was used.

## Timing results

The table uses the harness's sign convention: **positive means faster** than
`main0001`. Each percentage is the median of the seven within-round percentage
improvements; brackets are its 95% percentile bootstrap interval (2,000 resamples).
Intervals describe repeated processes for these fixed builds, not uncertainty
across all possible builds. The ns columns are medians of the seven child medians.

| Build            | Acquisition 1, ns | Paired improvement, % | Acquisition 2, ns | Paired improvement, % |
| ---------------- | ----------------: | --------------------: | ----------------: | --------------------: |
| `main0001`       |            528.49 |             reference |            533.25 |             reference |
| `main0002`       |            532.73 |  −2.59 [−3.71, −0.27] |            546.90 |  −2.71 [−3.23, −1.88] |
| `main0003`       |            558.29 |  −5.47 [−7.23, −3.38] |            550.77 |  −4.19 [−4.54, −2.67] |
| `same0001` (A/A) |            526.17 |  +1.28 [−2.39, +1.93] |            526.40 |  +0.38 [−0.41, +1.31] |
| `cand0001`       |            526.36 |  +0.23 [−2.38, +1.87] |            531.09 |  −0.29 [−0.47, +0.14] |
| `cand0002`       |            526.33 |  +0.34 [+0.01, +1.43] |            520.33 |  +1.87 [+1.26, +2.69] |
| `cand0003`       |            526.89 |  +0.30 [−2.18, +2.81] |            524.37 |  +0.98 [+0.81, +2.90] |

There is no consistent candidate slowdown against the first baseline build.
The two other builds of the baseline source were 2.59–5.47% slower by the paired
statistic, a larger difference than any candidate slowdown. A/A intervals include
zero in both acquisitions. This does not establish equivalence or an improvement
from the candidate's code, nor does it identify the cause of build variation.

Across the two acquisitions, `shared_hit_medium` build medians ranged from
418.81–427.17 ns across baseline builds and 414.61–419.72 ns across candidates;
`capture_array` ranged from 226.66–230.64 ns and 48.83–49.50 ns respectively.
The latter is about 78% faster in the candidate with this workload order.
The [historical report](../process-memory/summary.md#differences-on-unchanged-code)
documents heap-state sensitivity in both controls. These new timings alone do
not establish the cause of their differences; the controls are not invariant
reference costs. No new heap perturbation or counter instrumentation was added.

## Publication checks and stopping condition

A separate diagnostic copy checked that every `store` and `publish` returned a
value and every `unpublish` returned true before releasing the payload. It ran
100 passes of 1,024 cycles for each of the six wheels: 614,400 checked cycles
without an assertion failure. This copy was not timed or used for training.

The primary timing slowdown was not reproduced reliably, so the issue's stopping
condition applies. Publication and reclamation were not timed separately, and no
unprofiled builds or microarchitectural investigations were needed. Neither
production code nor the training workload was changed. The historical public
benchmark is the available evidence about complete shared-cache reads and
publications; this follow-up makes no new production performance claim.

## Historical aggregation discrepancy

The recorded medians, 366.6 → 378.4 ns, imply a slowdown of
`100 * (378.4 / 366.6 - 1) = 3.2188%`, not 1.6%.
The retained historical report does not contain enough information to reconstruct
the separately reported paired statistic or its permutation p-value. Its exact
aggregation remains unverified; it must not be presented as the ratio of those
medians or as an allocator-controlled timing result.

The distinction is observable in the supported harness: acquisition 1's
`main0002` has a ratio-of-medians slowdown of 0.80%, but a median within-round
slowdown of 2.59%. Acquisition 2's `cand0001` has a ratio-of-medians improvement
of 0.40%, but a median within-round slowdown of 0.29%. Pairing and aggregation can
change both magnitude and sign. This explains why the two kinds of statistic
need not agree; it does not reconstruct the historical +1.6%.

## Reproduce

Use the [contributor environment](../../CONTRIBUTING.md#environment) and the
[historical reproduction prerequisites](../process-memory/summary.md#test-cost-and-reproduction).
Run in Bash from the repository root. This builds six fresh release wheels and
keeps raw results outside Git. All measured children use the historical candidate
interpreter and dependencies. Retain the shell variables for the diagnostic below.

```bash
set -euo pipefail
mkdir -p /tmp/agents
scratch=$(mktemp -d /tmp/agents/publish-cycle.XXXXXXXX)
export UV_LINK_MODE=copy
git worktree add --detach "$scratch/main" 4e071dfd5904527545177cd2e6f5bdb78a2239c9
git worktree add --detach "$scratch/candidate" 94065fbff5439c47268bd38e85b2101c95f9f30f
driver="$scratch/candidate"
mkdir -p "$scratch/overlays" "$scratch/results"
for tree in "$scratch/main" "$driver"; do
    (cd "$tree" && uv sync --locked --no-default-groups --group build)
done
for label in main0001 cand0001 main0002 cand0002 main0003 cand0003; do
    case "$label" in
        main*) tree="$scratch/main" ;;
        cand*) tree="$driver" ;;
    esac
    (cd "$tree" && CARGO_TARGET_DIR="$scratch/targets/$label" just build)
    uv pip install --python "$driver/.venv/bin/python" --no-deps \
        --target "$scratch/overlays/$label" "$tree"/dist/*.whl
done
cp -a "$scratch/overlays/main0001" "$scratch/overlays/same0001"
cd "$driver"
for seed in 20261102 20261114; do
    .venv/bin/python -m research.native_build_profile.compare \
        --overlay-root "$scratch/overlays" --python "$driver/.venv/bin/python" \
        --baseline main0001 --labels main0002 main0003 same0001 cand0001 cand0002 cand0003 \
        --rounds 7 --cpu 2 --seed "$seed" \
        --workloads shared_hit_medium shared_publish_cycle capture_array \
        --output "$scratch/results/timing-$seed.json"
done
```

Run the separate untimed diagnostic after timing. The assertions leave training
and the primary benchmark unchanged:

```bash
cat >"$scratch/diagnostic.py" <<'PY'
from scripts.pgo_training import SharedIndex, SMALL_BYTES, DATABASE, SHARED_NAMESPACE, EPOCH

shared = SharedIndex(SMALL_BYTES)
for _ in range(100):
    for identity, encoded in zip(shared.identities, shared.payloads, strict=True):
        fresh = shared.index.store(encoded)
        assert fresh is not None
        token = shared.index.publish(
            DATABASE, SHARED_NAMESPACE, EPOCH, identity, shared.shape, fresh
        )
        assert token is not None
        assert shared.index.unpublish(fresh)
        shared.index.release(fresh)
PY
for label in main0001 main0002 main0003 cand0001 cand0002 cand0003; do
    PYTHONPATH="$scratch/overlays/$label:$driver" PYTHONHASHSEED=0 \
        setarch --addr-no-randomize taskset -c 2 "$driver/.venv/bin/python" "$scratch/diagnostic.py"
done
```

Each `timing-<seed>-runs/<label>-<round>.json` records the imported extension path,
SHA-256 and per-workload child medians; the top-level JSON records the paired
statistics. These raw outputs stay untracked. After preserving any needed local
results, return to the original checkout, move generated untracked build files
out of the worktrees, and remove both worktrees with `git worktree remove`.
