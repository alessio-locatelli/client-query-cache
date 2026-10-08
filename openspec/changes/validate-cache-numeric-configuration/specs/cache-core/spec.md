## ADDED Requirements

### Requirement: Cache budget fields require built-in integers

Each cache-budget field SHALL accept only an exact built-in integer. Boolean values, integer subclasses, floats including NaN and infinities, strings, null values, and other types SHALL raise the public configuration error at configuration construction, before comparisons or storage initialization.

#### Scenario: Invalid runtime budget input

- **WHEN** either shared-budget or maximum-entry configuration receives a non-built-in-integer value
- **THEN** construction raises `CacheConfigurationError` naming the invalid field
- **AND** no implicit conversion occurs

### Requirement: Cache budget ranges remain enforceable

Shared-budget and maximum-entry values SHALL be positive, and maximum-entry size SHALL NOT exceed the shared budget. Invalid relationships SHALL raise the public configuration error at configuration construction. Public configuration guidance SHALL state these constraints and the rejected input types.

#### Scenario: Valid boundary values

- **WHEN** both values are positive built-in integers and maximum-entry size equals the shared budget
- **THEN** construction succeeds with the values unchanged

#### Scenario: An invalid range or relationship is supplied

- **WHEN** either value is zero or negative, or maximum-entry size exceeds the shared budget
- **THEN** construction raises `CacheConfigurationError` describing the violated constraint
