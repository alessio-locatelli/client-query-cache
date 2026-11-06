# Spec Delta

## ADDED Requirements

### Requirement: Shared managers export worker-scope counters

Registration SHALL accept a shared manager of either execution model and export that manager's hits, misses, ordinary bypasses, oversized bypasses and per-reason bypasses under the existing instrument names, using the manager's own reason vocabulary for the `cache.bypass.reason` attribute. Values SHALL describe only that worker.

#### Scenario: An application registers a shared manager

- **WHEN** an application registers a shared manager with its own meter and a collection cycle runs
- **THEN** the counters equal the manager's `snapshot()` values and each bypass reason is a distinct observation

#### Scenario: A process-local manager is registered

- **WHEN** an application registers a process-local manager
- **THEN** its instruments, values and attributes are unchanged

### Requirement: Shared registration omits owner-scope instruments

Registering a shared manager SHALL NOT create capacity, entry, resident-byte or stream instruments and SHALL NOT issue any request to the owner during registration or collection. It SHALL NOT report zero-valued substitutes for omitted measurements.

#### Scenario: Metrics are collected from a shared manager

- **WHEN** a collection cycle runs for a registered shared manager whose owner is stopped
- **THEN** no owner request is attempted and no capacity or stream observation is reported
