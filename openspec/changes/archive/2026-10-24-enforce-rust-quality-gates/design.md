# Design

## Context

See proposal.md for scope and motivation. The crate is a Linux `cdylib` shipped through maturin, not a published Rust API. CI currently repeats its tests in every Python lane.

## Decisions

### Keep Cargo's native test runner

The current native suite is small. Retain `cargo test` and the existing optimized Loom run; use the CI job timeout to bound execution. Nextest provides per-test isolation and timeouts but adds another executable without a demonstrated need here. Tokio, semver checking, Miri, fuzzing, mutation testing, and Criterion address separate workloads rather than the requested baseline. No additional research is necessary for these exclusions.

### Share commands and tool versions

Use just recipes from local hooks and CI. Pin cargo-shear and cargo-deny in a single setup recipe with Renovate ownership. Install project tools into an ignored project-local directory so setup does not change system packages. Keep the existing compiler selection; missing formatter or Clippy components fail visibly with the official setup reference.

A new tool manager would add another bootstrap and update policy. An independently pinned compiler would conflict with the current Fedora/runner ownership; neither is required to enforce source checks. No further research is necessary.

### Enforce relevant lint and dependency policies

Run Clippy with warnings denied for the Python extension and Loom configurations. Remove the blanket non-Python suppression from production validation; retain only justified harness-specific diagnostics. Use cargo-shear for unused dependencies/unlinked files and cargo-deny for advisories, compatible licenses, duplicates, and crates.io-only sources. Do not duplicate cargo-check or cargo-audit work already performed by those checks.

Enabling every restriction or pedantic lint would impose unrelated stylistic policy and casts without demonstrated correctness benefits. Enable targeted safety diagnostics where useful instead. Cargo-deny's license allowlist follows the actual dependency graph, with no speculative allowances. The resolved graph passes cargo-deny and cargo-shear; no separate research is needed.

### Separate native CI from Python compatibility

Use one static native job and one dependent native test/model job. Include native policy, setup recipes, shared toolchain, Python test sources, and relevant lockfiles in their selection. Remove the repeated Cargo test steps from the Python matrix. Preserve independently visible prerequisite checks and document the required-check implications without changing hosted repository settings.

## Risks / Trade-offs

- Dependency advisories need network access: failures remain visible rather than becoming informational.
