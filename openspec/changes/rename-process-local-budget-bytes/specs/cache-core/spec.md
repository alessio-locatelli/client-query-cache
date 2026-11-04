# Spec Delta

## MODIFIED Requirements

### Requirement: Cache storage has a shared bounded budget

Each cache manager SHALL enforce one configurable weighted BSON memory budget, `CacheCoreConfig.budget_bytes`, shared by its collections. It SHALL evict least-recently-used entries as needed and SHALL reject entries larger than its maximum entry size.

#### Scenario: A new value exceeds the budget

- **WHEN** a cache admission would exceed the configured `budget_bytes`
- **THEN** the manager evicts eligible least-recently-used values or declines an oversized value without exceeding the budget

### Requirement: Cache budget fields require built-in integers

Each cache-budget field SHALL accept only an exact built-in integer. Boolean values, integer subclasses, floats including NaN and infinities, strings, null values, and other types SHALL raise the public configuration error at configuration construction, before comparisons or storage initialization.

#### Scenario: Invalid runtime budget input

- **WHEN** either `budget_bytes` or `max_entry_bytes` receives a non-built-in-integer value
- **THEN** construction raises `CacheConfigurationError` naming the invalid field
- **AND** no implicit conversion occurs

### Requirement: Cache budget ranges remain enforceable

`budget_bytes` and `max_entry_bytes` SHALL be positive, and `max_entry_bytes` SHALL NOT exceed `budget_bytes`. Invalid relationships SHALL raise the public configuration error at configuration construction. Public configuration guidance SHALL state these constraints and the rejected input types.

#### Scenario: Valid boundary values

- **WHEN** both values are positive built-in integers and `max_entry_bytes` equals `budget_bytes`
- **THEN** construction succeeds with the values unchanged

#### Scenario: An invalid range or relationship is supplied

- **WHEN** either value is zero or negative, or `max_entry_bytes` exceeds `budget_bytes`
- **THEN** construction raises `CacheConfigurationError` describing the violated constraint

### Requirement: Cache health is inspectable

The manager SHALL expose immutable health, capacity (including the configured `budget_bytes`), hit, miss, eviction, and bypass observations through publicly importable result types, without returning document values, queries, credentials, or resume tokens.

#### Scenario: An application inspects the manager

- **WHEN** an application requests a cache inspection snapshot
- **THEN** it receives immutable lifecycle, capacity (including the configured `budget_bytes`), hit, miss, eviction, and bypass observations in publicly importable result types, without document values, queries, credentials, or resume tokens
