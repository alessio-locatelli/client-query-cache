# Stream startup coordination measurements

Measured on 2026-10-08 with Python 3.14.6 in Fedora Toolbx, comparing parent
`e5f724a` with the `fix-stream-startup-coordination` implementation. These are local
coordination measurements using scripted streams, excluding MongoDB and network latency.

## Results

Each fresh process measures 10,000 healthy activations, 10,000 failed-database
activations, and activation of database B while database A's watch is gated for
100 ms. Healthy timings are the median of 20 batches after two warmup batches.
The table reports medians across 21 fresh processes per revision and execution
model, alternating revision order. Profiling runs separately from timing.

| Workload                                           | Synchronous parent | Synchronous candidate |    Async parent | Async candidate |
| -------------------------------------------------- | -----------------: | --------------------: | --------------: | --------------: |
| 10,000 healthy activations                         |           0.788 ms |              0.767 ms |        2.564 ms |        2.586 ms |
| Healthy timing range across processes              |     0.778–0.825 ms |        0.747–0.899 ms |  2.540–2.686 ms |  2.533–4.803 ms |
| 10,000 failed activations                          |         213.710 ms |              2.606 ms |      200.224 ms |        4.622 ms |
| Startup attempts / warnings for failed activations |    10,000 / 10,000 |                 1 / 1 | 10,000 / 10,000 |           1 / 1 |
| B activation with A gated                          |         101.565 ms |              0.273 ms |      101.086 ms |        0.068 ms |
| B completes before A is released                   |                 No |                   Yes |              No |             Yes |

Every process produced the reported attempt/warning counts and independence
outcome. The failed database uses a connection failure, with the candidate's
monotonic clock held at 10 seconds so subsequent reads remain before its deadline.
The warning handler counts records without formatting tracebacks or writing logs.

The healthy medians differ by −2.6% synchronously and +0.8% asynchronously, with
overlapping timing ranges. Investigation with `cProfile` found the same healthy
call counts in both revisions: 30,004 synchronous calls and 60,004 async calls for
10,000 activations. The coordinator and local lock operations dominate these
profiles; successful activation adds no retry-policy calls. These measurements
show no meaningful healthy-path regression. Retry amplification and serialization
behind another database's startup dominate the affected scripted workloads.
Real server startup latency remains outside this measurement.

## Reproduction

The committed harness is `benchmarks/stream_startup.py`. It uses the shared
scripted streams and databases in `tests/stream_fakes.py`, a real `CacheCore`, and
one healthy stream before timing repeated activation. Its failing script contains
10,000 `ConnectionFailure` entries. The two-database probe gates A's first watch,
starts B, checks completion before releasing A after 100 ms, and closes each
coordinator. Raw measurements and profiles remain untracked.

Run from the implementation checkout. `PYTHONPATH` selects each revision's
production code while retaining the committed harness and shared fakes from this
checkout; each JSON result records the loaded coordinator source path.

```sh
git worktree add --detach /tmp/cqc-stream-parent e5f724a
mkdir -p benchmark-reports/stream-startup
for repetition in $(seq 1 21); do
    set -- parent candidate
    if [ $((repetition % 2)) -eq 0 ]; then
        set -- candidate parent
    fi
    for mode in synchronous asynchronous; do
        for revision in "$@"; do
            checkout="$PWD"
            if [ "$revision" = parent ]; then
                checkout=/tmp/cqc-stream-parent
            fi
            PYTHONPATH="$checkout/src:$PWD" uv run -- python -m benchmarks.stream_startup "$mode" \
                > "benchmark-reports/stream-startup/$revision-$mode-$repetition.json"
        done
    done
done
```

Run profiles separately from the timing trials:

```sh
for mode in synchronous asynchronous; do
    PYTHONPATH="/tmp/cqc-stream-parent/src:$PWD" uv run -- python -m benchmarks.stream_startup "$mode" \
        --profile "/tmp/cqc-parent-$mode.prof"
    PYTHONPATH="$PWD/src:$PWD" uv run -- python -m benchmarks.stream_startup "$mode" \
        --profile "/tmp/cqc-candidate-$mode.prof"
done
uv run -- python -m pstats /tmp/cqc-candidate-synchronous.prof
```

Sort profiles by `tottime`. The deterministic concurrency and shutdown
reproductions are retained in `tests/stream_startup/`:

```sh
just pytest tests/stream_startup -q -n 0
```
