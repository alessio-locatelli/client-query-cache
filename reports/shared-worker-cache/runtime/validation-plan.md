# Fresh validation design

Discovery completed eighteen healthy windows in 832.21 seconds. Cached-path first-five-second versus settled-period P99 differences have two-sided 95% intervals within 0.066 ms; the direct path's interval spans -0.715 to +0.486 ms. Thus shortening primary hot measurement is not selected. Measurement windows, cold identities, paired-block counts, capacity and faults stay unchanged except for the active-window alternatives below. Warmup remains ten seconds for this validation.

## Baseline qualification

[qualification.json](qualification.json) freezes one fresh qualification window at each of the 38 baseline family/path/model/worker combinations, using the already frozen version 8 rates and schedules. Qualification uses the existing overload, completion, error, backlog and sample-floor checks. One failure makes the proposed calibration inconclusive; no candidate observations select rates. The proposed future calibration starts from conservative historical baseline rates and halves only from failed baseline qualification. Every later candidate window must still satisfy the same health checks. Independent capacity measurements remain mandatory. This evaluates replacing repeated saturated probes and three validation repetitions, without changing candidate inference or its input observations.

Estimated qualification execution is 30–40 minutes. It is not a rerun of the 294-window baseline calibration.

## Active duration validation

[validation.json](validation.json) freezes new observations, disjoint from discovery. Six mixed eight-worker blocks cycle all six path orders; three durations rotate through all three within-path positions twice. Four pure-model/worker cells each receive an additional paired 60/27.6-second diagnostic. Those four single-block comparisons establish workload/health coverage, not independent statistical precision.

| Condition | Duration | Writes |       Cadence | Complete lag captures | Mixed reads/model |
| --------- | -------: | -----: | ------------: | --------------------: | ----------------: |
| Reference |     60 s |    200 | one per 0.3 s |                   six |            30,180 |
| Short     |   27.6 s |     92 | one per 0.3 s |                 three |      about 13,883 |
| Smaller   |   20.1 s |     67 | one per 0.3 s |                   two |      about 10,110 |

All paths retain the same read rate, query/data mix and fresh clients/workers/cache. The lower write count explicitly reduces the number of distinct invalidated identities while preserving cadence; it does not preserve 200 writes. Existing lag capture configuration retains twenty events per capture and sixteen-event gaps.

Before these fresh measurements, the original conservative clustered-request model gives 27.6-second mixed populations a P99 power lower bound of 81.9% and boundary-error upper bound of 3.31%. Thirty seconds gives 84.5% and 2.58%. The approximately 10,000-sample smaller condition fails the original 80% power requirement in that model; it is retained as a real comparison rather than assumed optimal from its sample floor. Six-second active windows would retain only twenty writes and roughly 3,018 mixed samples/model; the original population search rejects such large reductions under clustering. Block counts remain twelve for subsequent candidate acceptance, with the original bootstrap seeds/draws/omission rule.

For each path, compare paired duration statistics in the mixed cell. Two-sided nominal 95% paired-bootstrap intervals for mean differences must lie within +/-0.10 ms for request P95 and +/-0.25 ms for P99, within +/-50 ms for lag P95, and within +/-5% of the reference mean for CPU/read, MongoDB bytes/read and group memory. Every window must be healthy and preserve its declared schedules, expected invalidations and latency populations. An inadequate bound defers the duration change; it does not trigger repeated sampling for a pass. These criteria also test resource and lag effects beyond the read-quantile simulation. Supplemental cells must remain healthy and expose any changed candidate verdict.

Compare one, two and three retained lag captures against six in all twelve historical version 8 active blocks, including known additive effects near the absolute and relative lag limits. Historical resampling is an iid-block sensitivity, not capture-count validation; its power/error bounds cannot select the capture count. Twelve blocks cannot establish correlation uncertainty reliably. Fresh validation supplies the duration and lag evidence. Report correlation, uncertainty and rare-stall limitations explicitly. No sequential stopping or changed seed may rescue an unsuccessful condition.

Estimated validation execution is 75–90 minutes, with a 115-minute cap. Combined qualification and validation are approximately two hours; approval is required before a multi-hour batch under issue #278. Both scripts, configurations and analysis rules are reviewable before that approval. The cumulative investigation ceiling remains 24 hours, including setup and validation.
