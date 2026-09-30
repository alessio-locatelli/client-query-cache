# Design

## Context

Prek, Prettier, Python validation, and the PR performance guard run in separate pull request workflows. Job dependencies only work within one workflow, so these jobs currently start independently. The Python workflow uses a path filter to avoid documentation-only test runs.

## Decision

Consolidate the pull request jobs in `test.yml`. A lightweight path selection job reports whether changed files require Python or formatting validation. Prek runs for every pull request. Formatting installs Node and runs its checks only for matching paths. Package, Docker, and guard jobs depend on successful Prek and formatting jobs; package and Docker jobs also require the Python path output. The guard retains its own more specific comparison scope.

The scope check compares the pull request merge commit against the base revision using a full-history checkout. A failed diff or selector fails the scope job, so dependent jobs cannot silently proceed with an empty selection. Package, Docker, and guard jobs remain mutually independent after their prerequisites pass.

## Trade-offs

The scope and formatting jobs each reserve a runner for every pull request, even when formatting work is skipped. This preserves a successful dependency result without making the expensive jobs use an `always()` override for skipped prerequisites. A path selection job also adds a short startup delay before formatting.

The merged workflow changes workflow-level check identity. Existing branch rules that name the retired workflow contexts need to be updated outside the repository.
