# Historical stream-cost measurements

These 0.1.0 observations support the workload/resource trade-off illustrated
in public guidance. They predate the native cache engine and are not current
performance estimates. The matrix at `cf3c1ff` used Python 3.14.6, PyMongo 4.18.1,
MongoDB 8.0.4, one isolated replica-set member, one CPU and 1 GiB server memory.
The retained output did not identify client CPU/kernel details, limiting
cross-host interpretation. No confidence intervals were acquired.

## Balanced resource comparison

Each cell seeded 100 documents, warmed two reads, then sampled 50 reads and
50 writes (seeds 6/7/8 for small/medium/large). Reads preceded writes rather than
running concurrently. Payload profiles were 200/2,000/20,000 bytes.
Raw and cached runs used separate disposable collections. CPU includes each
whole MongoDB run; the difference is not isolated stream CPU. Bytes cover only
the dedicated client/container connection, excluding unrelated traffic.

| Payload profile | Raw / cached MongoDB CPU, s | CPU change | Received bytes change | Sent bytes change |
| --------------- | --------------------------: | ---------: | --------------------: | ----------------: |
| Small           |         0.057811 / 0.071912 |     +24.4% |                +57.2% |            −11.4% |
| Medium          |         0.064072 / 0.080596 |     +25.8% |                −55.0% |            −11.4% |
| Large           |         0.073944 / 0.077959 |      +5.4% |                −94.5% |            −11.4% |

Avoided document fetches outweighed polling traffic only for the larger
documents in this sample. These very short single-run observations neither
establish stable percentages nor predict interleaved-write behavior. Idle,
read-heavy and write-dominant matrix cells used 0/0, 100/10 and 10/100 sampled
reads/writes; they provide no additional retained decision claim.

## Consolidated stream decision

At `a2106ef`, three control/loaded pairs tested one database stream routing two
relevant collections while unrelated writes ran. Each side scheduled forty
relevant writes at 100 ms intervals and captured four ten-event lag windows.
The [decision input](decision-pre-registration.json) specifies clock uncertainty,
resampling and thresholds. All pairs met the 500 ms absolute lag and 100 ms
added-lag criteria, supporting keeping serial database routing for that workload.
Python 3.14.6/PyMongo 4.18.1/MongoDB 8.0.4 and one CPU/1 GiB were recorded.
Lag includes server and transport time; undetected clock steps between calibration
samples remain a limitation. This is not a throughput or cross-host guarantee.

## Reproduce

For the historical measurements, check out the named source and use its locked
contributor environment. For fresh current-code measurements:

```bash
uv run -- python -m benchmarks.stream_cost.run --direct-path-proxy --output-dir /tmp/agents/stream-cost
uv run -- python -m benchmarks.stream_cost.decision_evidence --output /tmp/agents/stream-decision.json
```

Choose a new output path each time and keep raw results untracked. Current
workload/report definitions are maintained in the
[developer protocol](../../../docs/development/stream-cost-benchmarks.md).
