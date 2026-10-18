# Tasks

## 1. Shared collection reads

- [x] 1.1 Add namespace selection and shared scalar/command-cursor execution using existing classification and capture helpers; verify public sync/async cross-process reuse, bypasses and invalidation for all six methods.
- [x] 1.2 Expose the existing find adapters publicly and cover modifiers, partial consumption, errors/cancellation, clone/rewind, bounds and hit snapshots.
- [x] 1.3 Update manager comparisons, API/deployment guidance, Context7 and a runnable multi-process filtered-read example; verify the example.

## 2. Performance acceptance

- [x] 2.1 Reuse benchmark harnesses to compare the existing identity path against main and report separate cold/hot workloads for new reads against PyMongo and independent caches, including concurrency, writes, sizes, CPU, tail latency and combined memory; record bounded reproducible evidence in Markdown.

## Code Quality

- [x] 3.1 Scan whole edited test files against AGENTS.md, including parametrization.
- [x] 3.2 Claude prose restriction is inapplicable: implemented by Codex.

Performance evidence: [collection-read measurements](https://github.com/alessio-locatelli/client-query-cache/blob/main/reports/shared-worker-cache/collection-reads.md).
