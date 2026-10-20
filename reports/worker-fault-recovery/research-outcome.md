# Worker fault-recovery study outcome

V8 stopped as inconclusive at the registered observer-overhead gate. The full
fault matrix did not run, no registration was frozen, and no recovery-time or
performance claims were established. The v1–v8 configurations and detailed
registration reports were removed with the quantitative trial machinery; this
file is the retained record of the study outcome.

The registered workload was copied from
[`reports/concurrent-worker-workload/v1/config.json`](../concurrent-worker-workload/v1/config.json),
SHA-256 `2057af0088101622b441f977fbc9bd78397f2e023fafd8b092cc1e74d1b6d0bc`.
The raw smoke, calibration and observer outputs were kept outside version
control under `benchmark-reports/worker-fault-recovery/`.

| Version | Recorded outcome                                                                                                                                                                                                                                                                                                                                |
| ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| V1      | No matrix ran. Smoke recovered 6/7 cells; independent worker restart missed the P99 criterion. The selected workload also failed the null-fault check.                                                                                                                                                                                          |
| V2–V3   | V2 smoke failed all 7 cells before injection at 150 requests/second. V3 reduced smoke to 100 requests/second; 5/7 cells recovered.                                                                                                                                                                                                              |
| V4–V5   | V4 smoke passed 7/7; calibration selected 2,849 requests/second, but 2 validation windows exceeded write-schedule tolerance. V5 smoke passed 6/7; stepdown/direct reported an unregistered `NotPrimaryNoSecondaryOk` error.                                                                                                                     |
| V6      | Smoke passed 7/7. Steady calibration validated at 1,431 requests/second; stepdown selected 4,362 requests/second, with 4/6 validation windows exceeding write-schedule tolerance.                                                                                                                                                               |
| V7      | Smoke passed 7/7. Steady calibration passed at 689 requests/second; 2/6 stepdown windows exceeded write-schedule tolerance at 2,232 requests/second.                                                                                                                                                                                            |
| V8      | Smoke passed 7/7 and null-fault checks passed 18/18 at both observer cadences. Calibration selected 692 requests/second for steady windows and 1,000 for stepdown. At 250 ms, 4/6 observer comparisons exceeded the worker-CPU limit. The 1 s retry still failed direct repetition 0 on request P99 and independent repetition 0 on worker CPU. |

The observer gate required instrumented request P99 to stay within the larger
of 10% or 0.2 ms of the uninstrumented result, and worker CPU per request to
stay within 10%. V8's preregistered stop rule required stopping after the 1 s
observer retry remained inconclusive. The planned matrix was 35 windows and 82
minutes of observation; startup, shutdown, drain and topology setup added an
unmeasured 2.5–3 hour estimate. No freeze digest, complete fault matrix, or
quantitative recovery analysis exists. Resuming requires a new registration
and a small pilot that establishes an observer method before any full matrix.
These historical outcomes are not operational guidance.
