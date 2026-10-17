# Tasks

## 1. Process-local namespace lifecycle

- [x] 1.1 Add and validate `CacheCoreConfig.max_namespaces`; make process-local managers bypass with `namespace_capacity` when registration is full, and cover configuration boundaries and overflow in core and manager tests.
- [x] 1.2 Fence captures with their originating namespace state and a non-reused generation token; release state on drops and verify a delayed admission cannot survive drop/recreate.
- [x] 1.3 Route drop, drop-database, rename-source and stream invalidation through namespace reclamation; cover each lifecycle event in `tests/core/test_stream_events.py`.
- [x] 1.4 Bound process-local collection and unique-key metadata maps by the core limit; verify capacity eviction and a stable retained-allocation plateau across repeated distinct namespace churn.
- [x] 1.5 Verify delayed eviction and unique-key cleanup cannot recreate or mutate a dropped namespace after its name is reused.

## 2. Shared namespace slots and worker metadata

- [x] 2.1 Pass `SharedCacheConfig.namespaces` to the owner core and workers; make `IndexPublisher` recycle released slots without retaining epochs for unassigned namespaces, and verify reuse with a one-slot owner.
- [x] 2.2 Bound sync and async worker metadata and slot maps by the attachment limit; verify eviction, refresh, stale-reader rejection after slot reuse and owner-incarnation fencing in shared-cache tests.
- [x] 2.3 Verify collection drops serialize with shared metadata slot assignment and leave the released slot reusable.

## 3. Public contract

- [x] 3.1 Update cache configuration, shared collection-name guidance, maintainer memory notes and Context7 rules to describe the bounded active set, drop reclamation and safe capacity bypass.

## 4. Code Quality

- [x] 4.1 Review every edited test file against the repository writing-test guidelines, including parameterization and fixture-owned cleanup.
- [x] 4.2 Check code prose requirements (OpenAI Codex; no Claude-specific restriction applies).

## Workflow follow-up

- After implementation and review, synchronize the delta specs, archive this change, validate the archive and commit the completed change as required by `AGENTS.md`.
