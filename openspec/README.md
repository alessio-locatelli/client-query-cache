# Active change roadmap

This repository treats the existing Python package as a proof of concept. Start with the bootstrap changes; do not begin cache-feature work until their local commands and tests are complete.

## Execution order

1. [`bootstrap-development-environment`](changes/archive/2026-09-06-bootstrap-development-environment/) establishes `uv`, locked dependencies, formatting, linting, and type checking. (Archived; see [its main spec](specs/development-environment/spec.md).)
2. [`bootstrap-test-environment`](changes/archive/2026-09-06-bootstrap-test-environment/) creates the unit, integration, end-to-end, and coverage foundation.
3. [`add-just-workflow`](changes/archive/2026-09-06-add-just-workflow/) consolidates setup and quality commands behind `just` recipes and a toolbx/Distrobox container image, wrapping the pytest tiers and Testcontainers fixture the previous change established.
4. [`add-continuous-integration`](changes/archive/2026-09-07-add-continuous-integration/) runs those completed local gates on GitHub Actions.
5. [`recover-proof-of-concept`](changes/archive/2026-09-07-recover-proof-of-concept/) replaces the experimental inheritance-based boundary with supported composition.
6. [`implement-cache-core`](changes/archive/2026-09-10-implement-cache-core/) adds bounded local cache primitives.
7. [`implement-change-stream-coherency`](changes/archive/2026-09-11-implement-change-stream-coherency/) makes cache use safe through database-scoped invalidation and recovery.
8. [`implement-cached-read-api`](changes/archive/2026-09-13-implement-cached-read-api/) exposes supported synchronous and asyncio cached reads.
9. [`benchmark-change-stream-costs`](changes/benchmark-change-stream-costs/) measures the completed cache under controlled workloads.
10. [`document-public-library`](changes/document-public-library/) documents the implemented public interface and operations model, including guidance linked to those reports.
11. [`add-release-verification`](changes/add-release-verification/) verifies distributable artifacts without publishing them.

Each change owns one outcome. A later change may rely on an earlier change, but it must not reimplement its tooling, test topology, public contract, or benchmark protocol.

## Starting a feature session

Read this roadmap, then the selected change's proposal, design, specifications, and tasks. Confirm every preceding change is complete before applying a dependent change. If a proposed feature needs a new observable behavior, create a new focused change rather than adding it to an unrelated active plan.
