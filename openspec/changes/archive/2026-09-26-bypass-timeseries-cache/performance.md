# Performance evidence

Measured on 2026-09-26 using Python 3.14.6, PyMongo 4.18.1, x86_64 Linux
7.2.7-200.fc44.x86_64, and disposable `mongo:8.0.4-noble` single-node replica sets.
Baseline source is commit `2769cb7`; updated source is the implementation
committed with this report. Dependencies and benchmark workload are unchanged.

## Workload and method

Use `benchmarks.stream_cost.guard_workload.run_case(uri, case, "small")` for
`sync_hit` and `async_hit`. Each timed sample is 256 primed `find_one` hits on a
200-byte document; the workload checks all returned values and hit/bypass counts.
Container startup, collection seeding, and manager creation are outside the timed
sample. The existing `tests.conftest.mongodb_uri` fixture supplies the replica set.

First collect seven samples per case on baseline, then seven on updated source.
These separate runs had wide sample variation and median increases of 3.91%
(sync) and 21.51% (async), so they do not isolate the code change from host noise.
To investigate, extract baseline `src/` with `git archive 2769cb7 src` and alternate
baseline and updated source in fresh subprocesses against one replica set: nine
blocks per case, baseline first on even blocks and updated first on odd blocks.
Set each subprocess's `PYTHONPATH` to the selected source tree and repository root,
use the same project Python, and execute the same `run_case` invocation. No test
suite ran concurrently with either measurement. Each sample seeds its own workload.

## Alternating comparison

| Case        | Baseline median (ms / 256 hits) | Updated median (ms / 256 hits) | Relative change |
| ----------- | ------------------------------- | ------------------------------ | --------------- |
| `sync_hit`  | 13.965                          | 13.974                         | +0.06%          |
| `async_hit` | 13.279                          | 11.991                         | -9.70%          |

The alternating sync medians are nearly equal, and the async median is lower.
Together with the wide initial variation, this provides no evidence of a stable
slowdown on this workload; it does not establish a speedup or a universal
performance guarantee. This is local diagnostic evidence, not the CI guard's
statistical decision procedure.

## Metadata calls

`test_collection_metadata_probe_counts` runs three missing-document reads per
collection kind in both execution models. Observed counts are:

| Collection kind   | Metadata probes | Cache hits |
| ----------------- | --------------- | ---------- |
| Existing ordinary | 1               | 2          |
| Time-series       | 1               | 0          |
| Absent            | 3               | 0          |

Ordinary hits add no metadata round trip. Repeated absent-name reads deliberately
pay for a probe and direct read every time. Time-series reads remain direct reads.

## Raw elapsed seconds

Each array preserves execution order within that case and revision.

```json
{
  "initial_base": {
    "sync_hit": [
      0.02217079099955299, 0.017590757999641937, 0.014490421999653336,
      0.020469891999709944, 0.021254819999739993, 0.019217709999793442,
      0.01072460300019884
    ],
    "async_hit": [
      0.012628976000087277, 0.011175859999639215, 0.019914212000003317,
      0.016248812999947404, 0.010955329999887908, 0.01380617999984679,
      0.018140230999961204
    ]
  },
  "initial_updated": {
    "sync_hit": [
      0.0237257579992729, 0.01996894399962912, 0.017982741000196256,
      0.028118457999880775, 0.01495591900038562, 0.017889927999931388,
      0.036013628000546305
    ],
    "async_hit": [
      0.011660502000268025, 0.016015143000004173, 0.020208274000651727,
      0.021854284000255575, 0.011372597999979916, 0.016776144000687054,
      0.02327009199962049
    ]
  },
  "alternating": {
    "sync_hit": {
      "base": [
        0.01067096200040396, 0.013965369999823452, 0.020149058000242803,
        0.010975090000101773, 0.01416528199933964, 0.01789937200010172,
        0.013531516000512056, 0.014710788000229513, 0.011043301999961841
      ],
      "head": [
        0.017552134000652586, 0.01653738700042595, 0.014791587000217987,
        0.010665427000276395, 0.012837129000217828, 0.01304828299998917,
        0.01397426999938034, 0.013028328000473266, 0.016037450000112585
      ]
    },
    "async_hit": {
      "base": [
        0.01697340800001257, 0.012875307999820507, 0.011538435999682406,
        0.011973915999988094, 0.020640955999624566, 0.011754051000025356,
        0.023911946999760403, 0.013279265999699419, 0.013368369000090752
      ],
      "head": [
        0.01486747600029048, 0.011521788000209199, 0.011991328000476642,
        0.011465953999504563, 0.011626573000285134, 0.014425600999857124,
        0.013263827000628226, 0.013571596000474528, 0.011546503999852575
      ]
    }
  }
}
```
