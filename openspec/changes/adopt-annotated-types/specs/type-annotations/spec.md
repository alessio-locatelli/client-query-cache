# Spec Delta

## Purpose

Defines how repository code states value constraints and document shapes in type annotations, so that readers and tools find them in one machine-readable place rather than in prose.

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

Reusable constrained aliases SHALL be defined in one private library module, which SHALL be the only module that imports annotation-metadata types. Each alias SHALL have at least one use in the repository. Library modules SHALL import these aliases for type checking only.

#### Scenario: A second module needs a positive integer

- **WHEN** another module annotates a positive integer
- **THEN** it reuses the shared alias instead of declaring its own constraint

### Requirement: Annotation metadata is not runtime validation

Annotation metadata SHALL NOT replace runtime validation. Explicit checks SHALL remain authoritative for caller input wherever the library validates it, and no runtime validator SHALL consume the metadata.

#### Scenario: A caller passes a value outside an annotated range

- **WHEN** a caller passes a value that its annotation excludes
- **THEN** the outcome is determined by the library's explicit validation, exactly as without the annotation

### Requirement: BSON documents and JSON objects use object-valued aliases

Dictionary annotations of BSON documents SHALL use the shared BSON document alias. Dictionary annotations of JSON objects SHALL use the shared JSON object alias. Both aliases SHALL use `object` values so that use sites narrow a value before relying on its type. Keyword-argument bundles and option dictionaries are not documents and SHALL keep their own annotations.

#### Scenario: A test inserts a document literal

- **WHEN** a test annotates a document it writes to or reads from MongoDB
- **THEN** the annotation uses the BSON document alias and the type checker accepts the code without weakening value types to `Any`

#### Scenario: Options are forwarded as keyword arguments

- **WHEN** a dictionary is unpacked as keyword arguments into a PyMongo call
- **THEN** its annotation is not replaced by a document alias

### Requirement: Public numeric interfaces state their ranges

Public numeric configuration fields and parameters whose range the library validates, and public snapshot fields whose range the library guarantees, SHALL carry annotations that state that range.

#### Scenario: A user inspects a cache budget field

- **WHEN** a user or tool reads the annotation of a public cache budget or stream await-time setting
- **THEN** the annotation states the range that construction enforces

#### Scenario: A user inspects a snapshot counter

- **WHEN** a user or tool reads the annotation of a public snapshot hit, miss, or byte counter
- **THEN** the annotation states that the counter is non-negative
