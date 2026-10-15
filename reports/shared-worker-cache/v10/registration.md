# Shared worker cache: lower admission overhead

This study continues [issue #272](https://github.com/alessio-locatelli/client-query-cache/issues/272) against the public 0.8.0 library. [Version 9](../v9/registration.md) supplies the acquisition and inference protocol. Its existing results, and versions 7/8, remain frozen. The candidate is the first clean commit containing this registration and the mechanism below; record its Git revision in every report. Any subsequent implementation change invalidates this candidate's acceptance measurements.

## Candidate

The single `shared-index` candidate uses reusable [core guards](../../../src/client_query_cache/_core/locking.py) and adaptive [owner admission polling](../../../src/client_query_cache/_shared/coordinator.py). Two section objects per core replace per-entry generator context managers. Their nesting depths are thread-local, and both guard kinds retain namespace/LRU exclusion until their outermost exit. Native capture validation, core capture-before-validation ordering, cache publication, bounded queues and socket fallback retain their existing contracts.

The owner retains fifty-millisecond maintenance sweeps. Consuming admissions enables five-millisecond queue polling until fifty milliseconds after the latest nonempty drain. Quiet owners return to the maintenance cadence. Each drain keeps the configured per-connection limit; this changes neither queue capacity nor admission eligibility.

The [native writer](../../../native/shared-index/src/index.rs) copies whole atomic words directly from payload/key slices. A stack buffer joins fragments and packs the final partial word. Atomic ordering, publication fences and allocation classes do not change. Boundary tests cover empty fragments, cross-word concatenation, arena reuse and payloads spanning word/page boundaries.

Local admission reuses the publisher's existing namespace-slot assignment, and core admission reuses its loaded namespace state for capture release. Reset observers still publish epochs, and core capture still precedes native-token validation. Admissions cannot allocate a previously unassigned namespace slot.

Safety coverage includes nested guards, exception unwinding, cross-thread isolation, concurrent core operations, invalidation before/after native-token validation, unavailable/expired/restarted captures, malformed queue peers and sync/async fallback. Commit the reviewed implementation and this registration before acceptance timing. Exploratory profiles and development diagnostics do not contribute acceptance samples.

## Current baseline calibration

The public release caches collection namespaces in the independent path and changes native distribution metadata. The guard optimization also affects independent caches. Version 9's environment therefore does not establish source compatibility. This registration freezes the [current environment](environment.json) and authorizes a fresh baseline-only downward calibration, using the validated shortened acquisition procedure rather than another saturation search.

Start with the conservative 1,006/1,000/319 requests/s caps in [config.json](config.json), copied from version 9. Run the existing thirty-eight-window [baseline design](../runtime/qualification.json) against current direct and independent paths. Retain its workloads, warmup, durations, completion/backlog/error checks, percentile sample floors and cold all-miss requirement. Starting caps are fixed before observing this candidate, and no candidate observations may select a rate.

All thirty-eight baseline windows must pass. The qualification analyzer must verify clean committed sources, complete producer shutdown, the configuration digest, the recorded research implementation and every frozen environment field, including the compiled native binary's SHA-256. Record the physical host and baseline-source review separately from automated success. The source review for this registration records the baseline changes above; it does not claim compatibility with version 9's baseline revision.

If any baseline window fails, preserve that attempt and halve the affected family's rate. Recompute its hot/sensitivity duration with the existing sample-preserving duration rule and 120-second cap; keep active windows at sixty seconds with 200 writes. Commit the revised configuration before another baseline-only attempt. Allow at most three attempts including the initial caps, with no upward search. Missing evidence, an incompatible environment or exhausted attempts make the study inconclusive. Freeze the successful configuration before candidate timing.

## Candidate evidence

Inherit every version 9 performance phase, block count, sample floor, gate, balanced order, bootstrap seed/draw count and leave-one-out check. Run screening, confirmation, capacity, active, cold and sensitivity afresh. Run all seventy-five timed fault trials with the unchanged [version 8 fault configuration](../v8/fault-config.json). Preserve failed windows and the existing stopping rules.

After baseline calibration, collect cold evidence first. If any required cold bound fails or is unstable, stop without claiming acceptance and preserve the failed study. A passing cold phase still requires every remaining phase above; it cannot substitute for hot, active, capacity or fault evidence.

Issue #272 requires cold P95 and P99 upper bounds no more than 1 ms above direct reads at four and eight workers in both execution models, with passing hot, active, capacity and timed fault evidence. Report large-document and sorted-find sensitivity separately. Sorted finds remain outside this optimization's scope and cannot support a general promotion claim.

Budget approximately eleven hours for qualification and performance acquisition on the registered host, plus smoke, timed faults and analysis. Reuse exploratory diagnostics to reject an unsuitable candidate before incurring that cost; do not reduce the registered evidence to make it finish sooner.

## Reproduce

Use the [contributor environment](../../../CONTRIBUTING.md), clean committed sources and fresh output paths. Raw output remains untracked.

Build optimized native code with maturin's `--release`; `--locked` rejects dependency drift. These flags match the repository's release-build policy. The frozen environment identifies the resulting binary, so a different build must be registered before timing.

```bash
source scripts/testcontainers-bridge.sh
uv run -- maturin develop --release --locked
PYTHONPATH=. uv run -- python research/shared_cache_runtime/experiment.py --config reports/shared-worker-cache/v10/config.json --design reports/shared-worker-cache/runtime/qualification.json --output /tmp/agents/issue-272-continuation/v10-baselines.json
PYTHONPATH=. OPENBLAS_NUM_THREADS=1 uv run --with numpy==2.3.4 --with scipy==1.16.3 -- python research/shared_cache_runtime/analysis.py --config reports/shared-worker-cache/v10/config.json --qualification /tmp/agents/issue-272-continuation/v10-baselines.json --output /tmp/agents/issue-272-continuation/v10-baseline-decision.json
```

Proceed after both automated and manual checks pass. Run each registered performance phase with its registered block count (`--blocks 3` for capacity):

```bash
uv run -- python -m benchmarks.stream_cost.shared_cache.run --phase <phase> --config reports/shared-worker-cache/v10/config.json --output /tmp/agents/issue-272-continuation/v10-<phase>.json
uv run -- python -m benchmarks.stream_cost.shared_cache.analysis /tmp/agents/issue-272-continuation/v10-<phase>.json --config reports/shared-worker-cache/v10/config.json --phase <phase> --blocks <registered-blocks>
```

Faults remain separate:

```bash
uv run -- python -m benchmarks.stream_cost.shared_cache.run --phase fault --config reports/shared-worker-cache/v8/fault-config.json --output /tmp/agents/issue-272-continuation/v10-fault.json
uv run -- python -m benchmarks.stream_cost.shared_cache.analysis /tmp/agents/issue-272-continuation/v10-fault.json --config reports/shared-worker-cache/v8/fault-config.json --phase fault
```
