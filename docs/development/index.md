# Development documentation

Start with [CONTRIBUTING](../../CONTRIBUTING.md) for the development environment and validation commands.

- [Architecture](architecture.md): cache storage, read classification, and invalidation design.
- [Performance regression guard](performance-regression-guard.md): measurements and maintainer review policy.
- [Memory regression tests](memory-regression-tests.md): opt-in allocation checks, calibration, and failure traces.
- [Parallel test execution](parallel-test-execution.md): worker defaults, coverage, diagnostics, and serial troubleshooting.
- [Concurrency stress tests](concurrency-stress-tests.md): mixed CRUD, admission and recovery races, and longer local runs.
- [PyPI publishing setup](pypi-publishing-setup.md): repository and release setup.
- [CI validation caches](ci-validation-caches.md): validation tools, reusable state, and the tracked documentation tooling issue.
- [Executable version updates](executable-version-updates.md): update ownership and validation.
- [Causal invalidation barrier decision](decisions/defer-causal-invalidation-barrier.md): the deferred API and reopening criteria.
- [Causal invalidation barrier research](research/causal-invalidation-barrier.md): provenance, findings, and reproduction guidance.
- [Shared invalidation research](research/shared-invalidation-feasibility.md): multi-process measurements, coordination assessment, and reproduction guidance.
- [Shared worker cache research](research/shared-worker-cache-feasibility.md): shared-storage prototype, screening verdict, bottleneck attribution, and reproduction guidance.

Published library guides live in [docs/user](../user/index.md).
