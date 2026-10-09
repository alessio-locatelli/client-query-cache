# Spec Delta

## ADDED Requirements

### Requirement: Numbers that cannot be negative state their range

Repository Python code SHALL write every integer or floating-point type whose values cannot be negative as `NonNegativeInt`, `NonNegativeFloat`, or a narrower shared alias, including annotations, type arguments, type aliases, and `cast` targets. Numeric types whose domain includes negative values SHALL remain bare `int` or `float`.

#### Scenario: A counter is annotated

- **WHEN** a field, parameter, or return value holds a count that starts at zero and only increases
- **THEN** its annotation is `NonNegativeInt`

#### Scenario: A duration is annotated

- **WHEN** a field, parameter, or return value holds an elapsed time or a monotonic timestamp
- **THEN** its annotation is `NonNegativeFloat` or `PositiveFloat`

#### Scenario: A signed value is annotated

- **WHEN** a number can be negative, such as a sort direction, a hash, or a clock-skewed lag
- **THEN** its annotation remains `int` or `float`
