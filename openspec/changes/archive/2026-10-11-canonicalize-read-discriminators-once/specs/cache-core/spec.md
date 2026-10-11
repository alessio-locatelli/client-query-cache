# Spec Delta

## ADDED Requirements

### Requirement: Read executions reuse prepared discriminator trees

In both execution models, cache-eligible `find`, `aggregate`, `count_documents`, and `distinct` executions SHALL canonicalize their raw discriminator tree once and reuse its canonical tree for lookup and admission. A find execution SHALL also reuse its canonical family for compatibility checks and source metadata. Constant-size wrappers and canonical-key passthrough SHALL NOT rebuild the query tree.

#### Scenario: An exact hit is served

- **WHEN** an eligible read executes against a valid exact cache entry
- **THEN** it performs one raw discriminator-tree canonicalization and returns the cached result without another tree traversal for key preparation

#### Scenario: A miss is admitted

- **WHEN** an eligible read misses and successfully completes its native result
- **THEN** lookup and admission share the prepared canonical tree instead of independently canonicalizing the raw discriminator

#### Scenario: A find uses a covering source

- **WHEN** a positive-limit find checks a compatible resident source after its exact lookup misses
- **THEN** compatibility checks reuse the prepared family without canonicalizing the raw family again
- **AND** the lookup retains one hit and no miss when a covering source succeeds

#### Scenario: A find execution is restarted

- **WHEN** a find cursor is rewound or cloned and its final options change before the next execution
- **THEN** that execution prepares its own key from the final native options rather than reusing an earlier execution's key

### Requirement: Read key preparation preserves bypass precedence

Read key preparation SHALL retain the existing order of request-level bypass conditions, unsafe filter, unsafe projection or pipeline, uncanonicalizable key, and collection eligibility. Canonicalization failure SHALL record `uncanonicalizable_key` only when no earlier condition applies, then delegate to native execution with the original arguments and errors, without cache lookup or admission.

#### Scenario: Unsafe input also contains an uncanonicalizable value

- **WHEN** a request has an unsafe filter, projection, or pipeline and its discriminator also contains an uncanonicalizable value
- **THEN** the facade records the corresponding unsafe reason rather than an uncanonicalizable-key reason
- **AND** it performs no raw discriminator canonicalization

#### Scenario: A request-level bypass precedes unsafe input

- **WHEN** a request is session-bound, has an incompatible read profile, or has unsupported options, and also has unsafe or uncanonicalizable key inputs
- **THEN** its existing request-level reason wins and no discriminator canonicalization is attempted

#### Scenario: A safe discriminator cannot be canonicalized

- **WHEN** an otherwise safe request contains a NaN or unhashable discriminator value
- **THEN** it records one uncanonicalizable-key bypass before any collection eligibility probe
- **AND** native execution determines the returned result or error
