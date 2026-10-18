# Native admission queue saturation

This assessment addresses [issue #289](https://github.com/alessio-locatelli/client-query-cache/issues/289). It compares the public queue size with deliberately reduced capacity and an owner pause, then tests bounded socket fallback under the same read workload.

## Workload and interpretation

The [runner](../../../research/admission_saturation/run.py) reuses the isolated MongoDB replica-set infrastructure and retains each worker group across three passes to measure how admission losses affect subsequent reads. Each window starts a fresh public server and eight spawned worker processes, each with four synchronous reader threads. Every worker reads 256 distinct documents in each of three passes: cold, revisit and recovery. A 500 ms settling interval follows each pass. Document payloads contain 4,096 or 65,536 bytes; BSON documents and admission frames are larger. The cache budget is 256 MiB and the arena is 320 MiB, sufficient for the 2,048-document set, so eviction is not the intended source of misses. MongoDB has two CPUs and a 2 GiB memory limit.

The normal queue is 1,114,112 bytes per worker. Reduced queues contain twice the payload bytes, enough for one complete admission frame. Paused windows suspend only the disposable owner during the cold pass, then resume it before settling. These are deliberate fault injections. Normal windows leave the owner running and use public transport sizing; their synchronized, closed-loop cold bursts are a stress workload, not a production traffic estimate. The connected control establishes one data socket in every reader thread before measurement. Normal windows start those threads without data sockets.

Three repetitions rotate scenario order. Each pass contains 2,048 successful, identity-checked reads. Admission loss is dropped sends divided by misses; the runner also checks that successful sends plus dropped sends equal misses. Hit rate is hits divided by all reads. P99 is calculated over each pass's individual read latencies; reported latency values summarize window P99s, rather than pooling repetitions. Owner CPU includes the pass and its settling interval, measured with `psutil`; its 10 ms resolution limits interpretation of small differences. Connection setup for the connected control is excluded; connection setup caused by the mitigation is included.

The baseline is `ae422f36500fafd20b37707e4a1e2d4914c775ab` (`main`). No native source or build change was made between acquisitions; the candidate changes admission-drop signaling and local miss selection. No complete acceptance study is repeated, and these short measurements carry no inferential confidence claim. Synchronous concurrency is measured here; both synchronous and asynchronous endpoint behavior is covered by the queue-full tests.

## Baseline observations

| Payload | Scenario      | Cold admissions lost | Revisit hit rate | Third-pass hit rate |
| ------- | ------------- | -------------------: | ---------------: | ------------------: |
| 4 KiB   | Normal        |                   0% |             100% |                100% |
| 4 KiB   | Reduced queue |                   0% |             100% |                100% |
| 4 KiB   | Paused owner  |               10.94% |           89.06% |                100% |
| 64 KiB  | Normal        |         59.28–63.92% |     36.08–40.72% |        53.56–59.62% |
| 64 KiB  | Reduced queue |         50.20–59.33% |     40.67–49.80% |        54.35–59.57% |
| 64 KiB  | Paused owner  |               93.75% |            6.25% |        26.71–41.50% |

Each range spans three windows. The preconnected control loses no admissions at either payload size and reaches 100% hits on both later passes. Reduced capacity alone does not saturate the 4 KiB workload. At 64 KiB, saturation occurs with normal capacity and without pausing the owner, so it cannot be dismissed as fault injection. The variation between normal and reduced capacities does not establish a monotonic capacity effect: owner scheduling and drain activity vary across these short windows.

For the normal 64 KiB workload, the baseline median cold/revisit/third-pass P99s are 26.68/15.60/7.14 ms. Median owner CPU is 0.15/0.07/0.06 seconds, including settling. The normal 4 KiB control has median cold P99 19.98 ms and no repeat-read misses.

## Mitigation and measured costs

The candidate records a native admission drop only when enqueue fails and no data socket is available. Once an enqueue subsequently succeeds, future disconnected identity misses establish a data socket through existing owner selection. Queue enqueue remains first choice and existing bounded socket fallback handles subsequent queue pressure. Dropped unrelated messages do not trigger this transition. Connection capacity and queue sizes remain unchanged.

Waiting for a successful enqueue matters: an earlier candidate reconnected immediately after a drop and raised paused-owner cold P99 to roughly 250 ms. That candidate is rejected. The retained candidate keeps queue-only behavior while the queue remains full, then enables transport fallback after capacity returns. A later owner stall can still incur the existing bounded transport deadline.

| Payload | Scenario               | Candidate cold admissions lost | Candidate revisit hit rate | Candidate third-pass hit rate |
| ------- | ---------------------- | -----------------------------: | -------------------------: | ----------------------------: |
| 4 KiB   | Normal / reduced queue |                             0% |                       100% |                          100% |
| 4 KiB   | Paused owner           |                         10.94% |                     89.06% |                          100% |
| 64 KiB  | Normal                 |                     6.59–8.54% |               91.46–93.41% |                          100% |
| 64 KiB  | Reduced queue          |                     5.22–9.42% |               90.58–94.78% |                          100% |
| 64 KiB  | Paused owner           |                         93.75% |                      6.25% |                          100% |

Normal 64 KiB revisit and recovery passes have no further admission losses. Every window in both acquisitions completes its reads and eventual post-write checks; neither acquisition has a measured bypass in these phases. A paused owner still cannot admit values while suspended, so the candidate preserves the initial losses and improves subsequent warming.

The normal 64 KiB tradeoff is measurable:

| Metric                                                       |                Baseline |                Candidate |
| ------------------------------------------------------------ | ----------------------: | -----------------------: |
| Median cold-pass duration                                    |                  248 ms |                   319 ms |
| Median cold/revisit/third-pass P99                           | 26.68 / 15.60 / 7.14 ms | 32.64 / 21.66 / 15.49 ms |
| Median cold/revisit/third-pass owner CPU, including settling |    0.15 / 0.07 / 0.06 s |     0.24 / 0.04 / 0.01 s |
| Median summed application duration across three passes       |                  504 ms |                   484 ms |
| Median summed owner CPU across three passes                  |                  0.28 s |                   0.30 s |

The candidate performs substantially more admissions during the cold pass and shifts owner CPU into that pass. It improves warming but does not establish lower tail latency: P99 rises in this workload. The 4 KiB normal case retains zero drops and full later-pass hits; median cold P99 is 19.90 ms versus 19.98 ms baseline. Paused-owner cold P99 is 18.41 ms versus 23.00 ms at 4 KiB and 23.86 ms versus 22.52 ms at 64 KiB. Short window timing and thread scheduling produce variation; these are descriptive measurements, not proof that the small summed-duration differences will generalize.

[Issue #289](https://github.com/alessio-locatelli/client-query-cache/issues/289) owns the decision on accepting the additional cold-pass and tail-latency costs. The candidate requires explicit approval of that tradeoff under the repository performance policy; until then it remains a reviewable proposal.

## Safety and limits

The runner asserts that every pre-write read returns the expected identity and revision. After all passes and settling, it updates every measured document through MongoDB and requires every worker to observe revision 1 within ten seconds. This checks eventual invalidation and availability; it does not establish a stricter invalidation-latency guarantee or exercise a write racing queued admission.

The existing `tests/shared_cache/test_owner.py` tests separately cover full-queue socket fallback and skipped admission in both endpoint models, obsolete captures after writes/reset/unavailability, mutations during admission, and progress publication fencing. `test_admission_queue.py` covers concurrent complete-frame publication and operation ordering. The mitigation retains those queue, core-capture and publication paths.

## Reproduce

From the repository root, build the native extension with the existing project procedure, then run:

```bash
source scripts/testcontainers-bridge.sh
mkdir -p /tmp/agents/admission-saturation
uv run python -m research.admission_saturation.run --output /tmp/agents/admission-saturation/candidate.json
```

Use a fresh output path: the runner refuses to overwrite a report. To acquire a fresh baseline with the same instrumentation, create a disposable checkout and copy only the research driver into it:

```bash
git worktree add --detach /tmp/agents/admission-saturation/baseline ae422f36500fafd20b37707e4a1e2d4914c775ab
cp -r research/admission_saturation /tmp/agents/admission-saturation/baseline/research/
(
  cd /tmp/agents/admission-saturation/baseline
  source scripts/testcontainers-bridge.sh
  uv run python -m research.admission_saturation.run --output /tmp/agents/admission-saturation/baseline.json
)
rmw /tmp/agents/admission-saturation/baseline/research/admission_saturation
git worktree remove /tmp/agents/admission-saturation/baseline
```

Acquire runs sequentially without concurrent tests or benchmarks. The output includes individual latencies, counters, phase CPU, connection counts, source/native hashes and environment metadata. Keep raw output untracked. Temporary outputs are not durable evidence; the committed summary and runner permit fresh acquisition, not independent recomputation if those outputs are lost.
