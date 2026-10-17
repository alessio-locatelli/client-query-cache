# Proposal

## Why

Namespace-keyed bookkeeping currently outlives dropped collections, so a process that creates and removes collections with distinct names can retain metadata for every name it has seen. The shared index has a namespace-slot limit, but that limit does not bound the Python registries around it.

## What Changes

- Bound the number of namespaces each cache manager tracks and make capacity exhaustion bypass caching safely.
- Reclaim namespace state and shared index slots when collection lifecycle events prove a name is no longer active, while fencing stale admissions and reused slots.
- Bound the remaining process-local and worker-side namespace metadata and update the supported collection-name guidance.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `cache-core`: add a finite tracked-namespace limit, safe exhaustion behavior and lifecycle reclamation.
- `shared-worker-cache`: recycle bounded shared namespace slots and bound worker-side metadata under collection-name churn.

## Impact

Changes affect `CacheCoreConfig`, process-local and shared cache managers, change-stream lifecycle handling, shared-index publication, namespace metadata caches, tests, public configuration and collection-name guidance. No dependency or storage-format change is required.
