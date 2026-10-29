# Spec Delta

## ADDED Requirements

### Requirement: Process-local retention limits are optional

`CacheCoreConfig` SHALL expose `max_entries` and `max_key_bytes`, each defaulting to `None` (disabled) and otherwise accepting only a positive exact built-in integer. Invalid input SHALL raise `CacheConfigurationError` naming the field. Limits SHALL apply independently across all collections of one process-local manager in both execution models.

#### Scenario: Existing admission defaults are preserved

- **WHEN** neither limit is configured
- **THEN** admission has no additional count or key-size restriction and performs no key-size accounting

#### Scenario: A limit is configured independently

- **WHEN** one limit is a positive built-in integer and the other is `None`
- **THEN** construction succeeds and only the configured restriction applies

#### Scenario: Invalid retention limit input

- **WHEN** either limit is zero, negative, a Boolean, an integer subclass, a float, a string or another non-null non-integer value
- **THEN** configuration construction raises `CacheConfigurationError` before storage initialization

### Requirement: Retained record capacity includes aliases

After each completed mutation, resident values plus retained unique-key aliases SHALL NOT exceed `max_entries` when configured. Replacement SHALL count only the surviving record. Value admission SHALL reclaim aliases before evicting least-recently-used values as needed. Alias publication at capacity SHALL be declined without displacing a resident value. Captures and registered namespace state SHALL NOT count as resident records.

#### Scenario: Small results exhaust record capacity before BSON capacity

- **WHEN** a new value would exceed the record limit while BSON space remains
- **THEN** aliases are reclaimed first and least-recently-used values are evicted only as needed to admit the value within both limits

#### Scenario: One identity has many aliases

- **WHEN** publishing an additional unique-key alias would exceed the record limit
- **THEN** that alias is not retained, the native result and any admitted identity value remain available, and one alias retention decline with reason `entry_capacity` is recorded

#### Scenario: Replacement and concurrent mutation

- **WHEN** replacement, alias displacement and admission race
- **THEN** the completed mutations retain at most the configured number of records without deleting a newer replacement

### Requirement: Retained keys have a defined size charge

With `max_key_bytes` enabled, each value or alias SHALL have a per-record charge: the sum of shallow Python object sizes over its canonical key roots, recursively visiting tuples and counting each object identity once within that record. Shared namespace identifiers and canonical tag singletons SHALL be excluded. Scalar referents, storage indexes and allocator overhead SHALL be excluded; the charge SHALL NOT claim actual retained memory.

#### Scenario: A key contains repeated canonical subtrees

- **WHEN** a value key references the same tuple subtree more than once
- **THEN** the subtree contributes once to that record's charge, independently of sharing with other records

#### Scenario: Identity and alias roots

- **WHEN** sizing an identity value or unique-key alias
- **THEN** the charge includes identity plus read shape for the value, or alias key plus resolved identity for the alias

### Requirement: Key-size declines preserve native delivery

A candidate whose key charge exceeds `max_key_bytes` SHALL NOT be retained. Equality SHALL be admitted if other checks pass. A sizing failure SHALL decline retention. These decisions SHALL preserve native results, errors and cursor delivery, leave existing valid entries intact, and record respectively `key_size_limit` or `key_size_unavailable` once per declined value or alias publication.

#### Scenario: A large query returns a small result

- **WHEN** the encoded result fits the BSON limits but its key charge exceeds the configured key limit
- **THEN** the complete native result is delivered and the candidate is not retained

#### Scenario: Only a non-composite identity admission's alias is too large

- **WHEN** a non-composite identity admission's value fits its limits but its accompanying alias does not fit the key limit
- **THEN** the identity value can be admitted and only alias publication is declined

#### Scenario: A size boundary or sizing failure is reached

- **WHEN** the key charge equals the configured limit or sizing cannot complete
- **THEN** equality passes the key check, while failure declines retention without surfacing a sizing error to the read caller

### Requirement: Retention accounting follows current ownership

Eviction, alias removal, invalidation, replacement, namespace reclamation and close SHALL release the corresponding retention capacity. In-flight captures SHALL retain their existing generation and availability guards. Dropping an alias for capacity SHALL NOT invalidate its identity value. A closed manager SHALL report zero retained values and aliases.

#### Scenario: A capture outlives its resident entry

- **WHEN** eviction removes the last resident value while an identity capture remains active
- **THEN** any still-retained alias consumes capacity, and a later capacity reclamation can remove that alias without reviving stale admission

#### Scenario: A write or namespace lifecycle event releases records

- **WHEN** the existing lifecycle rules reclaim values or aliases
- **THEN** released records cease consuming capacity and later admission can reuse it

### Requirement: Retention inspection separates values and aliases

Cache snapshots SHALL expose `max_entries`, `max_key_bytes` and `alias_count`, retaining `entry_count` as the count of resident values and `used_bytes` as stored BSON bytes. Alias reclamation SHALL NOT increment value eviction counts. Inspection SHALL remain local and read-only without exposing keys.

#### Scenario: A miss admits a value but declines its alias

- **WHEN** alias capacity or key size prevents publication
- **THEN** inspection shows the retained value, no new alias and one matching retention decline, without changing bypass or oversized counts or reclassifying the original miss

#### Scenario: Repeated inspection

- **WHEN** either manager API or its advanced core is inspected repeatedly
- **THEN** equivalent snapshots expose the configured limits and counts without traversing retained keys or changing counters

### Requirement: Retention declines have separate recording semantics

Snapshots SHALL expose immutable cumulative `retention_declines` counts by record kind (`namespace_value`, `identity_value`, `alias`) and reason (`key_size_limit`, `key_size_unavailable`, `entry_capacity`). Each declined candidate SHALL record once. Unused alternative representations, aliases skipped after an identity-key failure and reclaimed old records SHALL NOT count as declines. These events SHALL NOT increment bypass or oversized counters.

#### Scenario: A value fits but its alias does not

- **WHEN** admission retains a value and declines its alias due to key size or count capacity
- **THEN** exactly one matching alias decline is recorded and the read's hit/miss and bypass observations retain their existing meanings

#### Scenario: Existing telemetry is collected

- **WHEN** an OpenTelemetry collection follows a retention decline
- **THEN** ordinary bypass totals, bypass reason series and oversized totals remain unchanged by that decline
- **AND** the decline is available through snapshot inspection without adding query-derived labels or redefining existing instruments

### Requirement: Count-enabled unique-key admission prefers a useful pair

With `max_entries` enabled, unique-key admission SHALL prefer an identity value and its alias as one useful pair, without adding a namespace value. If the pair cannot fit, it SHALL attempt the original namespace result instead. Pair failure SHALL NOT strand a newly admitted identity value or alias. Alias publication SHALL require a valid resident identity value; later alias retention SHALL follow existing capture and invalidation rules.

#### Scenario: One record fits

- **WHEN** an empty cache has `max_entries=1` and all candidate keys and value payloads individually fit
- **THEN** only the namespace value is retained and repeated original queries can hit
- **AND** one alias `entry_capacity` decline is recorded for the impossible pair without sizing its keys

#### Scenario: Two records fit

- **WHEN** an empty cache has `max_entries=2` and the identity key, alias key and single value payload fit
- **THEN** the identity value and alias are retained, the namespace value is absent, and both original unique-key and matching identity queries can hit

#### Scenario: Three records fit

- **WHEN** an empty cache has `max_entries=3` and the pair fits
- **THEN** only the pair is retained for that query, leaving a slot for another record

#### Scenario: The BSON budget fits only one value payload

- **WHEN** count capacity permits the pair but storing two copies of the result would exceed the BSON budget
- **THEN** pair admission requires only the identity value's usual BSON charge and no redundant namespace payload

#### Scenario: The original query key is too large

- **WHEN** the pair fits but the unused namespace key would fail its key check
- **THEN** the pair is retained without sizing or recording a decline for that unused key

### Requirement: Pair admission respects global occupancy and eviction

Pair feasibility SHALL use current manager-wide occupancy, exact replacements and alias reclamation atomically. It SHALL reuse valid matching records and respect normal value LRU. It SHALL NOT evict unrelated values beyond those needed to admit the identity value alone solely to obtain an alias slot. A failed pair plan SHALL make no destructive changes before namespace fallback is evaluated. Cleanup SHALL preserve newer replacements.

#### Scenario: A full cache cannot spare an alias slot

- **WHEN** a cache with `max_entries=2` holds two unrelated values and admitting the identity value alone would evict one
- **THEN** the pair does not evict the second unrelated value for its alias
- **AND** normal single-value admission of the namespace fallback is attempted instead

#### Scenario: Alias reclamation supplies the second slot

- **WHEN** the pair fits after reclaiming existing aliases and any normal identity-value LRU victims
- **THEN** those aliases can be reclaimed and the pair admitted without extra unrelated-value eviction for its alias

#### Scenario: Matching records already occupy capacity

- **WHEN** the matching identity value or alias already resides in the cache
- **THEN** the pair plan counts only net record and byte changes and validates their exact ownership and generations

#### Scenario: A redundant namespace record already exists

- **WHEN** replacing the exact current namespace record with the pair makes the pair feasible
- **THEN** that record can be retired as part of the atomic replacement without treating a newer replacement as redundant

#### Scenario: Admissions race across namespaces

- **WHEN** concurrent admissions compete for the same manager-wide capacity
- **THEN** each committed plan uses the latest occupancy and leaves the combined bound intact

#### Scenario: A warm hit changes the planned LRU victim

- **WHEN** a warm hit promotes a value after tentative victim selection but before eviction commits
- **THEN** admission revalidates victim selection against the new order without evicting an extra unrelated value for an alias

### Requirement: Pair fallback and admission outcomes remain explicit

With `max_entries` enabled, composite admission SHALL report admitted only for a valid resident pair or eligible namespace fallback. A fitting identity value alone SHALL NOT establish success. If neither representation fits, it SHALL report a retention decline. Stale and unavailable outcomes SHALL retain their generation and availability meanings. With `max_entries=None`, existing composite targets and outcomes SHALL remain, except for explicitly enabled key-size declines.

#### Scenario: The alias key cannot be retained

- **WHEN** the pair's alias key exceeds its limit but the original namespace key and result fit
- **THEN** namespace fallback is admitted without a newly stranded identity value or alias, and the outcome is admitted rather than stale

#### Scenario: No candidate value fits

- **WHEN** the pair fails and the namespace fallback key also fails its key check
- **THEN** admission reports a retention decline without changing existing valid records

#### Scenario: A write races preparation

- **WHEN** a sizing callback or another thread invalidates the capture before publication
- **THEN** the existing stale or unavailable outcome applies without publishing stale values or aliases

#### Scenario: Only the key-size limit is enabled

- **WHEN** `max_entries=None` and `max_key_bytes` is configured
- **THEN** the existing namespace-value, identity-value and alias publication policy is retained subject to its individual key checks, without enabling the pair-and-fallback policy

### Requirement: Pair fallback decline observations are deterministic

Count-enabled unique-key admission SHALL record one blocking pair decline plus any namespace-fallback decline. Structurally impossible pairs SHALL be rejected before key sizing; otherwise identity key checks SHALL precede dependent alias checks. Choosing the pair SHALL NOT count its omitted namespace value as a decline. Retries SHALL NOT duplicate observations or leave speculative residency changes.

#### Scenario: A pair fails but its fallback succeeds

- **WHEN** the alias is blocked by key size or count capacity and namespace fallback is admitted
- **THEN** one matching alias decline is recorded, with no decline for the uncommitted identity value or successful fallback

#### Scenario: Both useful representations fail

- **WHEN** the identity key fails, preventing an alias attempt, and the fallback namespace key also fails
- **THEN** the identity-key and namespace-key declines are recorded once each, with no alias decline

### Requirement: Key sizing adds no warm-hit traversal

Key-size accounting SHALL occur only for prospective retention, reuse its result within one admission attempt including retries, and retain no additional key copy. Exact, compatible and alias warm hits SHALL NOT recursively traverse keys for sizing. Disabled key limits SHALL NOT allocate sizing state.

#### Scenario: A large predicate repeatedly hits

- **WHEN** repeated reads hit an already resident value or compatible source
- **THEN** no key-sizing pass is performed

### Requirement: Public BSON budget naming is consistent

The process-local configuration and cache snapshot SHALL expose `budget_bytes` instead of `shared_budget_bytes`, without an alias. The value SHALL retain its manager-wide stored-BSON meaning and current validation rules. `max_entry_bytes` SHALL remain bounded by `budget_bytes`. Shared configurations SHALL keep their existing `budget_bytes` name and capacity policy.

#### Scenario: An application uses the renamed field

- **WHEN** it constructs configuration with `budget_bytes` and inspects its manager
- **THEN** the same configured BSON budget appears as `budget_bytes` and validation errors use that name

#### Scenario: An application uses the removed field

- **WHEN** it supplies `shared_budget_bytes` as a configuration keyword or reads that snapshot attribute
- **THEN** the removed interface is rejected rather than silently accepted
