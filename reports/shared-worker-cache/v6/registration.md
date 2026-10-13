# Shared worker cache: timed fault registration

This registration addresses [issue #273](https://github.com/alessio-locatelli/client-query-cache/issues/273). The frozen [config.json](config.json) is the source of truth for cases, applicability, repetitions, resource limits and deadlines. The frozen configuration SHA-256 is `9db07e7054f3217a54cab271553441b73381bc9e64651a897ea082fe88ca874e`. Versions 4 and 5 remain frozen and are not rerun.

The experiment uses one shared-index owner and four worker processes, two synchronous and two asyncio, against a disposable single-member replica set. Each of version 5's fifteen cases runs five times with fresh processes and data. The scripted hot set has 64 documents with 4 KiB payloads, a 1 MiB cache budget and a 1 MiB publication arena. These bounds keep transition trials short and force publication space reuse during churn. This is recovery evidence for that hot set, not a repetition of version 5's throughput or memory experiment.

Workers prime and verify the complete hot set before injection, except for shutdown during activation, which starts with attached, unprimed managers. Probes use one host monotonic clock. Detection ends only when every worker stops selecting the faulted state. Safe readiness requires owner availability and fresh upstream progress plus an eligible worker. Rewarming requires the hot set to be resident and locally published. The configured polling cadence is a minimum delay between unsuccessful observations; control round trips and scenario checks add observation delay, so durations are upper bounds on the first transitions observed by this script.

The driver checks incarnation changes and obsolete captures on restart, local fencing during owner stalls, capture rejection while the watch is expired, cache clearing after history loss, capture preservation after resumable interruption, capture reclamation on worker death, healthy-peer progress under backpressure and malformed input, native reads across startup shutdown, cancellation cleanup, and published-byte membership under concurrent churn. Recovered trials also verify a processed write through every worker. Safety failures and observation timeouts remain in the output. Inapplicable timings are JSON `null`; missing applicable timings fail analysis. The readiness gate is independent of the observation timeout.

## Reproduce

Build the native research component using the [version 5 instructions](../../../docs/development/research/shared-worker-cache-feasibility.md#reproduce-version-5), then run from a clean checkout:

```bash
source scripts/testcontainers-bridge.sh
uv run -- python -m benchmarks.stream_cost.shared_cache.run --phase fault --config reports/shared-worker-cache/v6/config.json --output benchmark-reports/shared-worker-cache/v6-fault.json
uv run -- python -m benchmarks.stream_cost.shared_cache.analysis benchmark-reports/shared-worker-cache/v6-fault.json --config reports/shared-worker-cache/v6/config.json --phase fault
```

The runner preserves each repetition before proceeding. Reusing a partial report requires `--resume <report>` and a new output path; analysis fails any missing repetition. Raw outputs remain untracked. A passing result supplies no evidence about the unresolved miss-latency criterion in [issue #272](https://github.com/alessio-locatelli/client-query-cache/issues/272) or version 5's failed capacity window, and does not establish production promotion.
