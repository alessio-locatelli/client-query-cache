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

## MODIFIED Requirements

### Requirement: Bare annotations need no permissive prose

Prose SHALL NOT merely restate that a bare numeric, string, or collection annotation admits zero, negative, or empty values, or explain an accumulator's empty initialization. Prose SHALL be preserved when it explains a sentinel, cache eligibility, or the conditions under which a collection is empty.

#### Scenario: An accumulator starts empty

- **WHEN** a list is initialized empty and filled later
- **THEN** its bare list annotation is sufficient and no comment explains the empty start

#### Scenario: An empty collection has domain meaning

- **WHEN** a comment explains that an empty result is cacheable or that a collection is empty for a particular workload or unresolved comparison
- **THEN** the comment remains because the annotation cannot express that behavior
