# Spec Delta

## Purpose

Defines how repository code states value constraints in type annotations, so that readers and tools find them in one machine-readable place rather than in prose.

## ADDED Requirements

### Requirement: Value constraints are stated in annotations

Repository Python code SHALL express sign, numeric bounds, and minimum or exact lengths of a value through annotation metadata, not through comments or docstrings. Prose MAY remain where it explains what a value means, for example a sentinel, a unit, or an index base, and no annotation can express that meaning.

#### Scenario: A field is documented as positive

- **WHEN** a field, parameter, or return value is only valid when positive
- **THEN** its annotation carries that constraint and no comment restates it

#### Scenario: A comment explains a sentinel value

- **WHEN** a comment states that zero denotes an unlimited limit
- **THEN** the annotation states the non-negative range and the comment keeps only the meaning of zero

### Requirement: Bare annotations need no permissive prose

Prose SHALL NOT state that a value with a bare numeric, string, or collection annotation can be zero, negative, or empty, or explain why such a collection starts empty, because the bare type already admits those values.

#### Scenario: An accumulator starts empty

- **WHEN** a list is initialized empty and filled later
- **THEN** its bare list annotation is sufficient and no comment explains the empty start

### Requirement: Shared constrained aliases have one source

Reusable constrained aliases SHALL be defined in one private library module, which SHALL be the only module that imports annotation-metadata types. Each alias SHALL have at least one use in the repository.

#### Scenario: A second module needs a positive integer

- **WHEN** another module annotates a positive integer
- **THEN** it reuses the shared alias instead of declaring its own constraint

### Requirement: Annotation metadata is not runtime validation

Annotation metadata SHALL NOT replace runtime validation. Annotations state a value's static type and range; explicit checks SHALL remain authoritative for caller input, including exact-type rules such as rejecting booleans, and no runtime validator SHALL consume the metadata.

#### Scenario: A caller passes a value outside an annotated range

- **WHEN** a caller passes a value that its annotation excludes
- **THEN** the outcome is determined by the library's explicit validation, exactly as without the annotation

### Requirement: Public numeric interfaces state their ranges

Public numeric configuration fields and parameters whose range the library validates, and public snapshot fields whose range the library guarantees, SHALL carry annotations that state that range.

#### Scenario: A user inspects a cache budget field

- **WHEN** a user or tool reads the annotation of a public cache budget or stream await-time setting
- **THEN** the annotation states the range that construction enforces

#### Scenario: A user inspects a snapshot counter

- **WHEN** a user or tool reads the annotation of a public snapshot hit, miss, or byte counter
- **THEN** the annotation states that the counter is non-negative

### Requirement: Public dataclass annotations resolve at runtime

Field annotations of every public dataclass SHALL resolve at runtime through `typing.get_type_hints`, including any constrained alias and its metadata.

#### Scenario: A configuration tool introspects the cache configuration

- **WHEN** a tool calls `typing.get_type_hints` with `include_extras=True` on a public configuration or snapshot dataclass
- **THEN** the call succeeds and each constrained field resolves to its alias, whose value carries the range metadata
