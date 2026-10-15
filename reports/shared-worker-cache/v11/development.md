# Admission polling diagnostics

These observations are exploratory and excluded from the [registered study](registration.md). The installed native build and workload match v10. The diagnostic owner overrides only `_ADMISSION_POLL_SECONDS` to `0.001` in its spawned process; tracked runtime sources remain at `1823ff9`. Each batch runs three balanced cold blocks, retaining the 1,000 requests/s rate and every other workload setting. All nine windows in each batch complete healthily.

| Model / workers | P99 delta over direct ms, blocks 1–3 | Owner CPU µs/miss, blocks 1–3 |
| --------------- | -----------------------------------: | ----------------------------: |
| async / 4       |                  0.834, 0.609, 0.991 |                 188, 187, 188 |
| sync / 8        |                  0.637, 0.699, 1.025 |                 239, 241, 243 |

These batches do not estimate a paired causal speedup and cannot establish confidence bounds or stability. The synchronous batch retains a block above the 1 ms limit. Faster polling consumes additional owner CPU; the complete capacity, hot and active gates still apply.

A separate one-block synchronous eight-worker diagnostic times owner methods with thread CPU and wall clocks. At five-millisecond polling, its 1,617 queue drains average 1.387 ms CPU and 1.407 ms wall time. Wrapper overhead changes execution cost, so these values motivate reducing bursts without estimating uninstrumented request latency. A separate GC-callback diagnostic finds collection pauses in both direct and shared workers without establishing a shared-only cause. Neither instrumentation run contributes acceptance samples.

## Reproduce

Copy v10's configuration under `/tmp/agents/`, changing only `phases.cold.blocks` to three. Save this diagnostic wrapper there, source `scripts/testcontainers-bridge.sh`, and run it with `PYTHONPATH=.` using the contributor environment:

```python
from benchmarks.stream_cost.shared_cache import owner, run, window
from client_query_cache._shared import coordinator


def fast_owner(config, control):
    coordinator._ADMISSION_POLL_SECONDS = 0.001
    return owner.owner_main(config, control)


if __name__ == "__main__":
    window.owner_main = fast_owner
    run.main()
```

Pass `--phase cold --only async:4` or `--only sync:8`, the diagnostic `--config` and a fresh `--output`. For each block, subtract direct request P99 from shared request P99 and divide shared owner CPU by completed requests. Retain all windows. Raw reports and instrumentation remain under `/tmp/agents/issue-272-continuation/`.
