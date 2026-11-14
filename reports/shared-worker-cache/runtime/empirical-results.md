# Shared-cache benchmark duration and qualification

The investigation of [#278](https://github.com/alessio-locatelli/client-query-cache/issues/278)
found an acquisition saving without shortening candidate windows: 38 fresh
conservative-rate qualification windows took 34.72 minutes, replacing at least
3.841 hours of saturation calibration. The roughly eleven-hour resulting study
duration was a forecast, excluding smoke, faults and analysis.

## Conditions and method

Fresh validation used `1b8fa7b58aafeaf3956f0752b1a2d439b3b71d47`, Python
3.14.7, PyMongo 4.18.2, Intel i3-13100 and disposable two-CPU/2-GiB MongoDB.
The default workload is frozen in [v8/config.json](../v8/config.json).
Each window recreated data, clients, workers, owner and cache. Qualification
and validation ran without tracing. The [qualification](qualification.json)
and [duration-validation](validation.json) inputs preserve cells and schedules.

All 38 qualification windows passed completion, backlog, error, sample-floor
and cold all-miss checks. This did not estimate rare-overload probability.
Rates require a matching host, baseline/workload and environment. A failed
qualification needs declared recalibration, not retries until pass; candidate
windows still need health checks and separate capacity evidence.

## Why shorter active windows did not qualify

Six mixed-model blocks compared 60 seconds/200 writes, 27.6 seconds/92 writes
and 20.1 seconds/67 writes at 1,006 reads/s and one write every 0.3 seconds.
Condition/path positions were balanced; four pure-model cells supplied coverage
diagnostics. Keeping cadence explicitly reduced total invalidated keys.

Equivalence margins were ±0.10 ms P95, ±0.25 ms P99, ±50 ms lag P95 and
±5% CPU/read, bytes/read and group memory, with paired nominal 95% bounds,
both seeds and every block omission. Shorter durations failed equivalence:
27.6-second direct P99 intervals reached −0.337 to +0.092 ms; shared bytes/read
fell 19.65–20.41%. At 20.1 seconds shared bytes/read fell 36.36–36.56%.
The catalogue revisit time was about 16.3 seconds: shorter stops allowed less
rereading of invalidated identities even at the same write cadence.

Keeping 200 writes in shorter windows would increase intensity. Six lag captures
of twenty events with sixteen-event gaps also require 200 events. Lower
durations therefore do not preserve this workload.

## Precision limits

Known-effect simulations searched 3/6/12/24 blocks and 1,000–60,000 requests.
Six blocks failed the predefined 80% power requirement even with independent
requests; three also failed the 5% false-acceptance requirement. Ten-request
clusters invalidated some apparently sufficient populations. Strong simulated
between-block dependence also invalidated the inherited protocol; these were
sensitivity assumptions, not fitted host-correlation estimates. More bootstrap
draws cannot replace observations.

Hot discovery failed to establish equivalence of ten-second windows. The selected
protocol kept thirty-second hot, sixty-second active and 32-second sensitivity
windows, twelve confirmation/active/cold blocks and 10,000 percentile samples.
This was the smallest validated protocol in the searched set, not a global optimum.

## Reproduce

Use the named source for historical acquisitions, or current code for a fresh
methodological study. The driver defaults to the retained v8 configuration.

```bash
source scripts/testcontainers-bridge.sh
PYTHONPATH=. uv run python research/shared_cache_runtime/experiment.py --design reports/shared-worker-cache/runtime/qualification.json --output /tmp/agents/qualification.json
PYTHONPATH=. uv run python research/shared_cache_runtime/experiment.py --design reports/shared-worker-cache/runtime/validation.json --output /tmp/agents/duration-validation.json
```

Historical v7/v8 retrospective analysis requires raw inputs outside Git.
Known-effect simulations can run independently with
`OPENBLAS_NUM_THREADS=1 uv run --script scripts/analyze_shared_cache_runtime.py
--simulate-only --output /tmp/agents/precision.json`. Keep raw outputs untracked;
fresh experiments reproduce the method, not the original tables.
