# Spec Delta

## ADDED Requirements

### Requirement: BSON documents and JSON objects use object-valued aliases

Dictionary annotations of BSON documents SHALL use the shared BSON document alias, and dictionary annotations of JSON objects SHALL use the shared JSON object alias. Both aliases SHALL use `object` values, so that use sites narrow a value before relying on its type.

#### Scenario: A test inserts a document literal

- **WHEN** a test annotates a document it writes to or reads from MongoDB
- **THEN** the annotation uses the BSON document alias and the type checker accepts the code without weakening value types to `Any`

#### Scenario: A benchmark writes a JSON report

- **WHEN** a benchmark builds a report object that it serializes with `json.dumps`
- **THEN** the report's annotation uses the JSON object alias

### Requirement: Option dictionaries are not documents

Keyword-argument bundles, option dictionaries, and read-only `Mapping` parameters SHALL NOT be annotated with the BSON document or JSON object alias.

#### Scenario: Options are forwarded as keyword arguments

- **WHEN** a dictionary is unpacked as keyword arguments into a PyMongo call
- **THEN** its annotation is not replaced by a document alias
