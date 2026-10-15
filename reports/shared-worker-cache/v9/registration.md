# Shared worker cache: qualified baseline rates

This protocol preregistration applies the validated acquisition reduction from [issue #278](https://github.com/alessio-locatelli/client-query-cache/issues/278) to future fresh studies, including the [issue #279 continuation](https://github.com/alessio-locatelli/client-query-cache/issues/279). The [empirical report](../runtime/empirical-results.md) records evidence and limitations. Commit this registration and the candidate declaration before candidate timing. Existing version 7/8 evidence and issue #272's outcomes remain frozen.

The single candidate family remains `shared-index`. Before timing, the continuation must commit its precise candidate mechanism, safety evidence and clean revision. This document freezes the protocol; it does not select an unimplemented optimization or reinterpret old measurements. A candidate changing query/data mix, baseline behavior, topology or workload semantics requires a new registration.

The [frozen configuration](config.json), SHA-256 `f1674a64f70b390beabc6c740b1e8c4cc4a64ae1d5874fdda2476f0f5d0a02e4`, differs from version 8 only in registration number and baseline validation repetitions (three → one). Generated candidate schedules and inference settings are unchanged. Primary/cold/sensitivity offered rates remain 1,006/1,000/319 requests/s; hot/active/sensitivity durations remain 30/60/32 seconds.

## Fresh baseline qualification

Before candidate timing, run the [qualification design](../runtime/qualification.json) with this configuration. It runs one fresh window at each of 38 direct/independent baseline combinations: twelve hot, ten active, eight cold and eight sensitivity. It preserves dataset, rate, duration, warmup and health checks. Each window recreates its catalogue, clients, workers and cache. No qualification observation becomes a candidate block.

The historical conservative rates apply only while baseline implementations, workload definitions, dependencies, server image, host and topology match the investigated environment. The analyzer compares all machine-verifiable fields with the canonical [registered environment](environment.json), including dependency versions, MongoDB image, hardware, topology, client options and native-extension metadata. It excludes `available_memory_bytes`, which varies during normal execution. Fresh qualification and every candidate window check runtime resource variation.

A successful automated result has `automated_checks_passed: true` and `status: "pending-manual-review"`; it is not fully qualified. **Before candidate timing, verify the same physical host and review baseline/workload changes against `1b8fa7b58aafeaf3956f0752b1a2d439b3b71d47`. Record both manual checks alongside the automated result.** Hardware labels cannot establish physical host identity, and the analyzer cannot establish baseline source compatibility. Shared-only candidate changes may differ; changes affecting direct/independent baselines, workload, dependencies, server image or host invalidate these starting rates.

The producer's cleanliness check includes `research/shared_cache_runtime/` and its numerical helper under `scripts/`, in addition to benchmark, native, library and report sources. It records that research scope; version 9 rejects reports without it. The analyzer requires the producer's recorded hash to match its committed Git revision, and requires the final elapsed-time marker written after container shutdown. Interrupted reports are incomplete even if every planned window is present. The candidate revision must be the clean revision declared for the new study.

Every qualification must pass `validation_failure`: errors, overflow, incomplete traffic, backlog, sample floors and cold all-miss behavior remain disqualifying. The analyzer rejects incomplete reports, missing/duplicate/unexpected windows, dirty or mismatched producer sources, incompatible environments and mismatched configuration digests. A failed automated check exits nonzero; a health failure records `status: "failed"`. Qualification establishes baseline quality, not candidate acceptance. Candidate windows retain ordinary runner health and inference checks.

A qualification failure or invalidated environment makes this registration inconclusive for that study. Do not discard failures, retry until passing, select rates from candidates or silently continue. Register and commit baseline-only recalibration first; preserve existing halving, sample-preserving duration, 120-second cap and bounded-attempt rules. Freeze its new configuration before fresh candidate measurements. No upward rate search belongs to this shortened procedure.

Probe fields remain because the existing registration schema requires them. They are compatibility fields: **the commands below replace `--calibrate-baselines` and `--freeze` for this protocol.** The old calibration command still performs saturated probes and would not implement the acquisition reduction.

## Candidate evidence

The [version 5 phase and inference rules](../v5/registration.md#phases-and-inference), inherited by version 8, remain authoritative:

- Run screening, confirmation, capacity, active, cold and sensitivity afresh. Keep six screening blocks, twelve confirmation/active/cold blocks and three sensitivity blocks, balanced path order, 10,000 gated-percentile samples, all seeds/draws and leave-one-out checks.
- Keep configured ten-second warmup. Cold retains no warmup and 10,000 new identities per window. Preserve large-document/sorted-find profiles and every capacity concurrency point/repetition.
- Active retains sixty seconds, 200 distinct writes at one per 0.3 seconds, six twenty-event lag captures and sixteen-event gaps. Shorter fixed-cadence windows failed fresh equivalence.
- All 75 fault trials remain required under the unchanged [version 8 fault configuration](../v8/fault-config.json), run fresh at the declared candidate revision. Fault evidence stays separate; readiness cannot replace first-hit safety.
- Preserve thresholds, failed-window reporting and stopping rules. Missing/skipped evidence cannot establish acceptance. Point diagnostics and investigation observations are excluded from candidate promotion.

## Reproduce

Use the [contributor environment](../../../CONTRIBUTING.md), clean committed sources and new output paths. From the repository root:

```bash
source scripts/testcontainers-bridge.sh
PYTHONPATH=. uv run -- python research/shared_cache_runtime/experiment.py --config reports/shared-worker-cache/v9/config.json --design reports/shared-worker-cache/runtime/qualification.json --output benchmark-reports/shared-worker-cache/v9-qualification.json
PYTHONPATH=. OPENBLAS_NUM_THREADS=1 uv run --with numpy==2.3.4 --with scipy==1.16.3 -- python research/shared_cache_runtime/analysis.py --config reports/shared-worker-cache/v9/config.json --qualification benchmark-reports/shared-worker-cache/v9-qualification.json --output benchmark-reports/shared-worker-cache/v9-qualification-decision.json
```

Proceed only after the second command succeeds **and both required manual checks above are recorded**. Run each performance phase with the ordinary runner:

```bash
uv run -- python -m benchmarks.stream_cost.shared_cache.run --phase <phase> --config reports/shared-worker-cache/v9/config.json --output benchmark-reports/shared-worker-cache/v9-<phase>.json
uv run -- python -m benchmarks.stream_cost.shared_cache.analysis benchmark-reports/shared-worker-cache/v9-<phase>.json --config reports/shared-worker-cache/v9/config.json --phase <phase> --blocks <registered-blocks>
```

Use `--blocks 3` for capacity analysis. For faults:

```bash
uv run -- python -m benchmarks.stream_cost.shared_cache.run --phase fault --config reports/shared-worker-cache/v8/fault-config.json --output benchmark-reports/shared-worker-cache/v9-fault.json
uv run -- python -m benchmarks.stream_cost.shared_cache.analysis benchmark-reports/shared-worker-cache/v9-fault.json --config reports/shared-worker-cache/v8/fault-config.json --phase fault
```

Use `--resume` only under the ordinary runner's matching-environment rule. Keep raw reports untracked. The future results record must identify candidate revision, configuration/environment digests, qualification decision and complete phase results. Budget about eleven hours for performance acquisition plus qualification on this host, with additional time for faults, smoke and analysis; another host requires baseline-only recalibration under a new registration.
