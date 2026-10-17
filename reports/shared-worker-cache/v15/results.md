# Version 15: issue #272 acceptance passes

Candidate `56a837b22c3264a0038333fac9d4f5c7fd37c893` satisfies [issue #272](https://github.com/alessio-locatelli/client-query-cache/issues/272). Every required cold, hot, capacity, active and timed-fault check passes. The complete study retains the [preregistered configuration](config.json), [environment](environment.json), rates, block counts and inference rules. Sorted-find sensitivity still fails; this result does not establish general promotion or expand the public shared-cache scope.

## Provenance and qualification

All reports identify the same clean candidate revision and frozen native binary. All thirty-eight fresh baseline windows qualify at primary/cold/sensitivity rates of 1,006/1,000/319 requests/s, taking 1,885.10 seconds. Automated qualification reports no failures. Its `pending-manual-review` marker is resolved by the following two manual checks:

- **Source compatibility:** relative to v14, shared adapters use native control queues independently of data sockets and retain default wire shapes per view. Independent cache code and the native relay model are unchanged. The rebuilt binary includes the immutable queue-capability getter and matches the frozen digest. Fresh qualification covers this checkout; no historical source-equivalence claim qualifies its baselines. External C and framing prototypes are excluded.
- **Physical host:** freezing, qualification and every candidate phase run through the same local Fedora Toolbx and host Podman bridge on the registered i3-13100 host, without a remote executor or migration. Execution-context review and matching environment metadata establish host continuity.

Both manual checks pass. Before acquisition, the complete Python suite reaches 100% coverage, all forty-four Rust tests pass, and all seven release-mode Loom models pass. Native code and benchmark/library implementation remain unchanged throughout acquisition.

## Complete acquisition

| Phase         | Healthy / planned windows | Decision                                            |
| ------------- | ------------------------: | --------------------------------------------------- |
| Qualification |                   38 / 38 | pass, including both manual checks                  |
| Smoke         |                     9 / 9 | instrumentation check only                          |
| Cold          |                 144 / 144 | all 8 comparisons pass                              |
| Screening     |                 108 / 108 | all 36 point comparisons pass; continue             |
| Confirmation  |                 144 / 144 | all 36 comparisons pass                             |
| Capacity      |                 162 / 162 | all 24 registered gates pass                        |
| Active        |                 180 / 180 | all 32 comparisons pass                             |
| Sensitivity   |                   36 / 36 | large-document comparisons pass; sorted finds defer |
| Timed faults  |                   75 / 75 | all 15 cases pass all 5 repetitions                 |

Every performance phase has zero completion failures. Required inferential phases retain both bootstrap seeds, 200,000 draws and every leave-one-out check; every required outcome is stable. Capacity retains all three windows at every registered point and the registered staircase/futility rules. Active acquisition retains sixty-second windows, 200 writes, mixed execution and the registered lag-capture windows/gaps. Fault acquisition retains the v8 configuration and applicability rules.

## Cold bounds

The limit is a 1 ms additive upper confidence bound over direct reads. Every cell contains twelve balanced blocks:

| Model | Workers | P95 point / upper ms | P99 point / upper ms | Outcome |
| ----- | ------: | -------------------: | -------------------: | ------- |
| async |       4 |        0.323 / 0.377 |        0.387 / 0.540 | pass    |
| async |       8 |        0.457 / 0.500 |        0.583 / 0.811 | pass    |
| sync  |       4 |        0.293 / 0.310 |        0.475 / 0.577 | pass    |
| sync  |       8 |        0.385 / 0.461 |        0.511 / 0.671 | pass    |

## Hot, capacity and active checks

Confirmation's worst upper bounds across required cells remain within every limit:

| Criterion                           | Worst upper bound |    Limit |
| ----------------------------------- | ----------------: | -------: |
| Group memory / independent          |             0.709 |    0.750 |
| Peak memory / independent           |             0.709 |    1.100 |
| Total resident memory / independent |             0.900 |    1.100 |
| Hit P95 / independent               |             0.492 |    0.750 |
| Hit P99 / independent               |             0.432 |    1.000 |
| Request P99 / independent           |             0.958 |    1.250 |
| Request P99 additive delta          |         -0.057 ms | 1.000 ms |
| CPU per request / independent       |             0.837 |    1.100 |
| Wire bytes / independent            |             0.458 |    1.100 |

Capacity passes all registered gates with no failed or missing window. Active comparisons also pass: worst request P99 ratio 0.946, additive upper delta -0.076 ms, CPU ratio 0.818 and wire ratio 0.682. Worst lag P95 upper bound is 16.20 ms against 500 ms; its additive upper delta is 4.33 ms against 50 ms. These are separate registered phase conclusions, not an additional confidence claim combining phases.

## Sensitivity limitation

All eighteen large-document comparisons pass. Sorted `find16` has six failures, with no completion failures:

| Model / eight workers | Group-memory upper ratio | Request-P99 upper ratio | CPU upper ratio |
| --------------------- | -----------------------: | ----------------------: | --------------: |
| async                 |                    1.033 |                   1.333 |           1.436 |
| sync                  |                    1.055 |                   1.450 |           1.473 |
| Limit                 |                    0.750 |                   1.250 |           1.100 |

The sensitivity analyzer therefore returns `shared-index: defer`. Sorted-find publication is explicitly outside #272 and outside the public shared-cache read scope. Its failures remain visible and prevent a general promotion claim; they do not invalidate this issue's completed `_id`-miss acceptance.

## Reproduction and evidence limits

The raw measurements, analyzer outputs and one-off orchestration scripts were not durably preserved and are no longer available in the study's temporary storage. The committed artifacts therefore cannot independently reproduce the original acceptance statistics. The procedure below collects and analyzes new measurements; it does not verify the original acquisition.

Use clean sources at revision `56a837b`, the frozen files above and the [registered procedure](registration.md). Keep fresh raw output paths untracked. Build with `uv run -- maturin develop --release --locked`, source `scripts/testcontainers-bridge.sh`, then run fresh baseline qualification and resolve both manual checks before candidate acquisition.

Use the [v10 command sequence](../v10/registration.md#reproduce) with `v15` configuration paths and fresh output paths of your choice. To analyze a collected performance phase, set `REPORT` to its raw JSON path, `PHASE` to its registered phase and `BLOCKS` to its registered block count. The executed analysis environment pins NumPy and SciPy explicitly:

```bash
OPENBLAS_NUM_THREADS=1 uv run --with numpy==2.3.4 --with scipy==1.16.3 -- python -m benchmarks.stream_cost.shared_cache.analysis "$REPORT" --config reports/shared-worker-cache/v15/config.json --phase "$PHASE" --blocks "$BLOCKS" > "${REPORT%.json}-analysis.json"
```

Run cold first, then screening, confirmation, capacity, active and sensitivity with their registered block counts. Then run faults using the registration's separate fault commands: both acquisition and analysis use `reports/shared-worker-cache/v8/fault-config.json`, and fault analysis omits `--blocks`. Inspect explicit verdicts, stability and completion failures; process exit status alone does not establish acceptance.
