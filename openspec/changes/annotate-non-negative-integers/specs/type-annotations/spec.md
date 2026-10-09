# Spec Delta

## ADDED Requirements

### Requirement: Integers that cannot be negative state their range

Repository Python code SHALL write every integer type whose values cannot be negative as `NonNegativeInt` or a narrower shared alias, including annotations, type arguments, type aliases, and `cast` targets. Integer types whose domain includes negative values SHALL remain bare `int`.

#### Scenario: A counter is annotated

- **WHEN** a field, parameter, or return value holds a count that starts at zero and only increases
- **THEN** its annotation is `NonNegativeInt`

#### Scenario: A sort direction is annotated

- **WHEN** an integer can be negative, such as a sort direction or a hash
- **THEN** its annotation remains `int`
