# Keep process-local and shared cache managers explicit

## Context

Applications choose between a cache within one process and a cache shared by trusted same-host workers. Shared caching requires a parent-owned server, a common trust boundary, and a different shutdown order. Process-local caching requires only a caller-owned PyMongo client.

The shared API deliberately exposes an explicit owner. The [public measurements](../../user/benchmarks/shared-cache.md) show that sharing is a workload choice: it reduces duplicated streams and values but has owner and miss costs.

## Decision

Retain `CacheManager` and `SharedCacheManager` as separate public entry points. Document the choice before either tutorial, while keeping their common collection-view and raw-read conventions aligned. `SharedCacheServer` remains an explicit parent-owned resource.

## Alternatives considered

A single `CacheManager(client, connection=None)` could reuse a familiar name, but the optional connection would change cached-operation coverage, diagnostics, platform requirements and ownership. It would still require an explicit server and could not make the two modes interchangeable. Compatibility would require preserving the existing classes or introducing a migration period without removing those conceptual differences.

A constructor that starts or discovers an owner automatically would simplify some call sites but introduce owner election, credential distribution and shutdown ambiguity. Starting a server in each worker would preserve the duplication sharing is meant to remove. Those costs are unjustified for the supported parent/worker model.

## Consequences

Users must make one explicit choice. A comparison near getting started and links from examples and API references make it discoverable. Shared caching has stricter codec and collation requirements; applications must preserve query predicates and use direct reads where freshness matters.

A unified interface can be reconsidered if cached-operation coverage and diagnostics converge and a proposed lifecycle preserves explicit parent ownership without implicit election or per-worker servers. This decision introduces no API migration or implementation requirement.
