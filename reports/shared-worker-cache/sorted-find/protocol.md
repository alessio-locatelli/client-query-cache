# Bounded sorted-find investigation

This is an exploratory follow-up to [v15](../v15/results.md) for [#290](https://github.com/alessio-locatelli/client-query-cache/issues/290). It cannot promote a public API. Public cursor delivery remains tracked by [#295](https://github.com/alessio-locatelli/client-query-cache/issues/295).

## Reused evidence and candidate choice

The v15 report records six sorted-find sensitivity failures, while supported identity workloads passed. Its raw measurements and profiles are unavailable. The v15 diagnostics attribute identity costs, not sorted-result costs, so they cannot establish a sorted-find speedup. The earlier [v5 cost-floor study](../v5/registration.md#floor-results) selects local-index access over owner coordination; its measurements concern single documents and justify investigating that existing family, not predicting sorted-result costs.

The candidate publishes already captured, positive-limit result payloads and reads exact shapes locally. It changes no native layout, codec, cursor capture, miss admission or public wrapper. Alternatives and correctness boundaries are in the active `optimize-shared-sorted-find` design.

## Bounded measurements

Before candidate timing, freeze the following diagnostic protocol:

- Derive the configuration from v15 by restricting `phases.sensitivity.profiles` to `find16`. Keep its three balanced blocks, eight workers, both execution models, all three paths, 319 requests/s, 32-second measurement windows, 10-second warmup, data, limits and observers.
- Check every window's health, completion and hit outcomes. Report each block; do not pool requests across blocks or calculate promotion confidence from these diagnostics. Retain failed windows. Baselines must complete the same scheduled work for a comparison to be usable.
- Use the existing collector for group PSS, combined worker/owner/server CPU, request latency, MongoDB wire bytes and owner IPC. Compare against direct and independent paths. A local hit should produce no selection RPC; verify that through owner counters and tests.
- Compare main and candidate with `benchmarks.public_shared_cache`, three repetitions and 2,000 samples per worker. Retain its four-worker sync/async hot and cold workloads and all three baselines, with the same native binary on both revisions. This exercises public adapters and MongoDB; it does not requalify v15's cold-tail or failure bounds.
- Measure processed invalidation at 1, 64 and 1,024 bounded published result shapes, with core authority and native unpublication. Use five batches per size and report CPU per write; each write must leave no local result publication. This answers whether constant-time native invalidation is warranted for the measured workload.
- Use a separate instrumented sorted-result run to attribute remaining costs. Exclude profile timings from the uninstrumented comparisons.

The final report records reproduction commands, source revisions and dependency/build versions. Raw output remains untracked. If resource savings remain insufficient, retain the optimized research mechanism and document the blocking costs without widening public support or adding another fallback architecture.
