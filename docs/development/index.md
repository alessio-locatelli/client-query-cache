# Development documentation

Start with [CONTRIBUTING](../../CONTRIBUTING.md) for the development environment and validation commands.

- [Architecture](architecture.md): process-local cache storage, read classification, and invalidation design.
- [Cache manager decision](decisions/keep-explicit-cache-managers.md): why public process-local and shared managers remain explicit.
- [Shared-cache internals](shared-cache.md): native capacity bounds, memory accounting and profile attribution.
- [Stream-cost benchmark protocols](stream-cost-benchmarks.md): report accounting, retained studies and reproduction commands.
- [Performance regression guard](performance-regression-guard.md): measurements and maintainer review policy.
- [Memory regression tests](memory-regression-tests.md): opt-in allocation checks, calibration, and failure traces.
- [Process memory measurements](../../reports/process-memory/summary.md): cached versus direct process memory by entry shape, retention after release, and reproduction guidance.
- [Parallel test execution](parallel-test-execution.md): worker defaults, coverage, diagnostics, and serial troubleshooting.
- [Concurrency stress tests](concurrency-stress-tests.md): mixed CRUD, admission and recovery races, and longer local runs.
- [PyPI publishing setup](pypi-publishing-setup.md): repository and release setup.
- [CI validation caches](ci-validation-caches.md): validation tools, reusable state, and the tracked documentation tooling issue.
- [Executable version updates](executable-version-updates.md): update ownership and validation.
- [Causal invalidation barrier decision](decisions/defer-causal-invalidation-barrier.md): the deferred API and reopening criteria.
- [Causal invalidation barrier research](research/causal-invalidation-barrier.md): provenance, findings, and reproduction guidance.
- [Shared invalidation research](research/shared-invalidation-feasibility.md): multi-process measurements, coordination assessment, and reproduction guidance.
- [Shared worker cache research](research/shared-worker-cache-feasibility.md): shared-storage prototype, screening verdict, bottleneck attribution, and reproduction guidance.
- [Concurrent worker workload research](research/concurrent-worker-workload.md): direct reads versus per-worker managers under concurrent writes, with latency, CPU, memory, and invalidation-lag estimates and reproduction guidance.

- [Invalidation scope research](research/invalidation-scope.md): anchored reads under interleaved writes, modeled alternatives, and miss-cost follow-ups.
- [Stream-assisted invalidation evaluation](research/stream-assisted-invalidation.md): projection costs and the outstanding net-benefit evaluation for insert partitions and update dependencies.

Published library guides live in [docs/user](../user/index.md).
