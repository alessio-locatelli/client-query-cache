# type-annotations Specification

## Purpose

Defines how repository code states value constraints in type annotations, so that readers and tools find them in one machine-readable place rather than in prose.

## Requirements

### Requirement: Value constraints are stated in annotations

Repository Python code SHALL express sign, numeric bounds, and minimum or exact lengths of a value through annotation metadata, not through comments or docstrings. Prose MAY remain where it explains what a value means, for example a sentinel, a unit, or an index base, and no annotation can express that meaning.

#### Scenario: A field is documented as positive

- **WHEN** a field, parameter, or return value is only valid when positive
- **THEN** its annotation carries that constraint and no comment restates it

#### Scenario: A comment explains a sentinel value

- **WHEN** a comment states that zero denotes an unlimited limit
- **THEN** the annotation states the non-negative range and the comment keeps only the meaning of zero

#### Scenario: A comment states an index base

- **WHEN** a comment describes a field as a zero-based index
- **THEN** the annotation states the non-negative range and the comment keeps that the index is zero-based

#### Scenario: A comment states an exact collection length

- **WHEN** a comment states that a list holds exactly six entries
- **THEN** the annotation states that exact length and no comment restates it

### Requirement: Bare annotations need no permissive prose

Prose SHALL NOT merely restate that a bare numeric, string, or collection annotation admits zero, negative, or empty values, or explain an accumulator's empty initialization. Prose SHALL be preserved when it explains a sentinel, cache eligibility, or the conditions under which a collection is empty.

#### Scenario: An accumulator starts empty

- **WHEN** a list is initialized empty and filled later
- **THEN** its bare list annotation is sufficient and no comment explains the empty start

#### Scenario: An empty collection has domain meaning

- **WHEN** a comment explains that an empty result is cacheable or that a collection is empty for a particular workload or unresolved comparison
- **THEN** the comment remains because the annotation cannot express that behavior

### Requirement: Shared constrained aliases have one source

Reusable constrained aliases SHALL be defined in one private library module, and each SHALL have at least one use in the repository. Other modules SHALL use annotation metadata inline only for a constraint no shared alias can express, such as an exact length.

#### Scenario: A second module needs a positive integer

- **WHEN** another module annotates a positive integer
- **THEN** it reuses the shared alias instead of declaring its own constraint

### Requirement: Annotation metadata is not runtime validation

Annotation metadata SHALL NOT replace runtime validation. Annotations state a value's static type and range; explicit checks SHALL remain authoritative for caller input, including exact-type rules such as rejecting booleans, and no runtime validator SHALL consume the metadata.

#### Scenario: A caller passes a value outside an annotated range

- **WHEN** a caller passes a value that its annotation excludes
- **THEN** the outcome is determined by the library's explicit validation, exactly as without the annotation

### Requirement: Public numeric interfaces state their ranges

Public numeric configuration fields and parameters whose range the library validates SHALL carry annotations that state that range. Public snapshot fields SHALL carry annotations stating the range they keep whenever callers respect the annotated ranges of public recording parameters, and those parameters SHALL carry their ranges.

#### Scenario: A user inspects a cache budget field

- **WHEN** a user or tool reads the annotation of a public cache budget or stream await-time setting
- **THEN** the annotation states the range that construction enforces

#### Scenario: A user inspects a snapshot counter

- **WHEN** a user or tool reads the annotation of a public snapshot hit, miss, or byte counter
- **THEN** the annotation states that the counter is non-negative

#### Scenario: A caller records logical event bytes directly

- **WHEN** a caller reads the annotation of a public method that records a logical event byte count
- **THEN** the annotation states that the count is non-negative, the range the snapshot total relies on

### Requirement: Public dataclass annotations resolve at runtime

Field annotations of every public dataclass SHALL resolve at runtime through `typing.get_type_hints`, including any constrained alias and its metadata.

#### Scenario: A configuration tool introspects the cache configuration

- **WHEN** a tool calls `typing.get_type_hints` with `include_extras=True` on a public configuration or snapshot dataclass
- **THEN** the call succeeds and each constrained field resolves to its alias, whose value carries the range metadata

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

### Requirement: Static narrowing adds no recurring runtime calls

Repository Python code SHALL NOT call `typing.cast()` on recurring application paths or inside benchmark measurement loops. Casts MAY remain in tests, benchmark setup or reporting, and application setup or report assembly executed at most a few times per application lifetime.

#### Scenario: A cached read narrows a decoded value

- **WHEN** a collection or cursor consumes a cached value
- **THEN** static narrowing introduces no runtime function call

#### Scenario: Instrumentation observes repeated commands

- **WHEN** benchmark instrumentation observes a command during a measurement
- **THEN** it performs no `typing.cast()` call

#### Scenario: Setup narrows untyped configuration

- **WHEN** application configuration is loaded at most a few times per application lifetime
- **THEN** a cast is permitted at that boundary

### Requirement: BSON documents and JSON objects use object-valued aliases

Dictionary annotations of BSON documents SHALL use the shared BSON document alias, and dictionary annotations of JSON objects SHALL use the shared JSON object alias. Both aliases SHALL use `object` values, so that use sites narrow a value before relying on its type. A document whose fields a timed benchmark region reads MAY instead use a `TypedDict` that states those fields, so that the region performs no runtime narrowing.

#### Scenario: A test inserts a document literal

- **WHEN** a test annotates a document it writes to or reads from MongoDB
- **THEN** the annotation uses the BSON document alias and the type checker accepts the code without weakening value types to `Any`

#### Scenario: A timed benchmark reads a document field

- **WHEN** a benchmark reads a document field inside its measured interval
- **THEN** the document's annotation states the field's type, and the measured interval contains no narrowing call

#### Scenario: A benchmark writes a JSON report

- **WHEN** a benchmark builds a report object that it serializes with `json.dumps`
- **THEN** the report's annotation uses the JSON object alias

### Requirement: Option dictionaries are not documents

Keyword-argument bundles, option dictionaries, and read-only `Mapping` parameters SHALL NOT be annotated with the BSON document or JSON object alias.

#### Scenario: Options are forwarded as keyword arguments

- **WHEN** a dictionary is unpacked as keyword arguments into a PyMongo call
- **THEN** its annotation is not replaced by a document alias
