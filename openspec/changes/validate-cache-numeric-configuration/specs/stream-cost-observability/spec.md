## ADDED Requirements

### Requirement: Lag-window numeric fields require built-in integers

Lag-window count, events per window, and event separation SHALL accept only exact built-in integers. Boolean values, integer subclasses, floats including NaN and infinities, strings, null values, and other types SHALL raise the public configuration error at configuration construction before telemetry allocation.

#### Scenario: Invalid runtime lag-window input

- **WHEN** any numeric lag-window field receives a non-built-in-integer value
- **THEN** construction raises `CacheConfigurationError` naming that field rather than failing later or retaining unbounded samples

### Requirement: Lag-window numeric ranges remain enforceable

Lag-window count and events per window SHALL be positive; event separation SHALL be nonnegative. Invalid values SHALL raise the public configuration error at configuration construction. Public configuration guidance SHALL state these constraints.

#### Scenario: Zero separation is valid

- **WHEN** count and events per window are positive built-in integers and separation is zero
- **THEN** construction succeeds with adjacent windows permitted

#### Scenario: A lag-window range is invalid

- **WHEN** count or events per window is zero or negative, or event separation is negative
- **THEN** construction raises `CacheConfigurationError` identifying the violated constraint
