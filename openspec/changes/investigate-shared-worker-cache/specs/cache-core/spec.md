# Spec Delta

These production changes apply only if the shared-cache investigation promotes an implementation.

## MODIFIED Requirements

### Requirement: Cache storage has a shared bounded budget

A standalone manager SHALL enforce one configurable weighted BSON budget shared by its collections. Managers explicitly attached to one shared worker group SHALL use that group's single budget across its databases and collections. Storage SHALL evict least-recently-used entries as needed and reject entries larger than its maximum entry size.

#### Scenario: A new value exceeds the budget

- **WHEN** a cache admission would exceed the configured shared budget
- **THEN** the manager evicts eligible least-recently-used values or declines an oversized value without exceeding the budget

#### Scenario: Another worker admits an entry

- **WHEN** an attached worker admits a result while the group is near its configured budget
- **THEN** admission uses the same resident budget and eviction order as every other attached worker rather than allocating another per-worker cache

### Requirement: Advanced cache inspection remains available

The advanced cache inspection interface SHALL remain available with measurements equivalent to manager inspection. Standalone advanced core access SHALL remain unchanged; shared mode SHALL expose local observations and SHALL NOT offer blocking remote mutation through that synchronous interface.

#### Scenario: An advanced caller inspects the cache

- **WHEN** a caller uses the advanced cache inspection interface
- **THEN** it exposes equivalent cache measurements for the same underlying state

#### Scenario: An attached caller accesses advanced observations

- **WHEN** an attached manager's advanced inspection handle is used
- **THEN** it supplies the same labelled local observations as manager inspection without a synchronous network operation or standalone mutation primitives

### Requirement: Manager access preserves stream-cost inspection

Both manager execution models SHALL expose per-database stream-cost snapshots and active-database discovery through synchronous, read-only accessors. Standalone measurement scope, cumulative counts, bounded lag samples and clock limitations SHALL remain unchanged. Shared observations SHALL identify group scope, incarnation and observation age without counting one upstream event once per attached worker.

#### Scenario: A caller reads stream measurements through a manager

- **WHEN** a caller requests stream-cost measurements or active measurement databases through the manager
- **THEN** the observations agree with the existing advanced inspection source for the same underlying state, without additional database requests or state mutation

#### Scenario: Several workers observe one upstream event

- **WHEN** two attached managers inspect group stream-cost observations
- **THEN** each observation identifies the group and its age, and does not present its shared event count as an independent worker's additional upstream work

## ADDED Requirements

### Requirement: Shared cache observations identify their scope and age

Shared manager capacity and outcome observations SHALL distinguish group-resident storage from worker-local operations and label their coordinator incarnation and observation age. Inspection SHALL remain synchronous, local and read-only. Missing or stale replicated observations SHALL be explicit and SHALL NOT certify cache readiness.

#### Scenario: A worker inspects state during coordinator loss

- **WHEN** shared state cannot be refreshed after transport loss
- **THEN** inspection identifies its unavailable or stale observation without blocking on RPC or reporting it as authoritative current readiness

#### Scenario: Independent operation recordings are combined

- **WHEN** monitoring compares shared workers' operation counters with group storage
- **THEN** labelled scope prevents summing the same resident bytes or upstream counts as if each worker owned another cache
