# Development documentation

Start with [CONTRIBUTING](../../CONTRIBUTING.md) for the development environment and validation commands.

- [Architecture](architecture.md): cache storage, read classification, and invalidation design.
- [Performance regression guard](performance-regression-guard.md): measurements and maintainer review policy.
- [Memory regression tests](memory-regression-tests.md): opt-in allocation checks, calibration, and failure traces.
- [PyPI publishing setup](pypi-publishing-setup.md): repository and release setup.
- [CI validation caches](ci-validation-caches.md): validation tools, reusable state, and the tracked documentation tooling issue.
- [Executable version updates](executable-version-updates.md): update ownership and validation.
- [Causal invalidation barrier decision](decisions/defer-causal-invalidation-barrier.md): the deferred API and reopening criteria.
- [Causal invalidation barrier research](research/causal-invalidation-barrier.md): provenance, findings, and reproduction guidance.

Published library guides live in [docs/user](../user/index.md).
