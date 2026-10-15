# Shared worker cache: shorter admission bursts

This study continues [issue #272](https://github.com/alessio-locatelli/client-query-cache/issues/272) after [version 10 fails cold P99](../v10/results.md). The single `shared-index` candidate is the first clean commit containing this registration and the one-millisecond admission polling change. Record its Git revision in every report. Subsequent implementation changes invalidate its acceptance measurements.

## Candidate and evidence

The candidate retains all [version 10 mechanisms](../v10/registration.md#candidate), reducing only the recent-admission polling interval from five milliseconds to one. Consuming admissions enables fast polling until fifty milliseconds after the latest nonempty drain. Capture cleanup and recency maintenance retain fifty-millisecond sweeps; quiet owners return to that cadence. Queue capacity, per-connection limits, fallback, admission eligibility and capture/publication fences remain unchanged. Deterministic timing tests verify the interval, maintenance cadence and return to quiet polling; real queues verify deadline activation and extension.

The [development diagnostics](development.md) motivate shorter owner bursts and remain excluded from acceptance. They do not select an offered rate or alter any workload or gate.

## Frozen protocol

Inherit version 10's complete baseline-only calibration and candidate-evidence protocol. The [configuration](config.json) differs only in registration number; the [environment](environment.json), including the compiled native binary digest, is identical. Reuse the matching optimized native build. Run fresh thirty-eight-window baseline qualification before candidate timing and record both automated and manual checks. Starting rates, downward-only halving rule, three-attempt cap, sample-preserving duration rules and failure retention remain unchanged.

Run the complete twelve-block cold phase first. Any failed or unstable required bound stops this study. A pass requires fresh screening (six blocks), confirmation (twelve), capacity (three windows at every required point), active (twelve), sensitivity (three) and all seventy-five timed faults. Preserve version 9's inference settings, sample floors, balanced order and every health/stability check. Report sorted-find sensitivity separately; it cannot support general promotion.

Issue #272 still requires cold P95 and P99 upper bounds no more than 1 ms above direct reads at four and eight workers in both execution models, with passing hot, active, capacity and timed-fault evidence. No historical phase substitutes for this candidate's required evidence. Budget approximately eleven hours for qualification and performance acquisition, plus smoke, timed faults and analysis.

## Reproduce

Use the [version 10 reproduction commands](../v10/registration.md#reproduce), replacing each `v10` configuration, qualification, output and analysis path with `v11`. The fault configuration stays at `reports/shared-worker-cache/v8/fault-config.json`. Keep all raw outputs untracked, use fresh output paths and inspect explicit analyzer verdicts and failures.
