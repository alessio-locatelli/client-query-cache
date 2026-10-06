# Spec Delta

## MODIFIED Requirements

### Requirement: Namespace-guarded keys encode every output-affecting input

A namespace-guarded entry SHALL use a namespace-prefixed key encoding every output-affecting input. Distinct query identities SHALL have distinct physical keys. Reuse SHALL be allowed only by an explicitly specified semantic-equivalence or compatible-result contract; without such a contract, differing inputs SHALL NOT reuse a result.

#### Scenario: Different queries against the same namespace do not collide

- **WHEN** two `find` or `aggregate` reads against the same namespace differ in filter, pipeline, projection, sort, limit, skip, or collation
- **THEN** distinct query identities have separate physical keys and cannot supply one another's results except through explicitly supported compatible-result lookup; sharing a physical identity requires an explicitly supported equivalence

#### Scenario: Different `distinct` fields do not collide

- **WHEN** two `distinct` reads against the same namespace and filter differ only in the field whose values are distinguished
- **THEN** they are admitted and looked up as separate namespace-guarded entries, so neither can return the other's value list

## ADDED Requirements

### Requirement: Proven find filter permutations share one namespace key

Find filters in the explicitly supported equivalence set SHALL share their filter representation. All other output-affecting inputs SHALL remain in the namespace-prefixed physical key, and unsupported filter forms SHALL retain their existing distinctions.

#### Scenario: Proven predicate permutations share one source key

- **WHEN** two find filters differ only in supported top-level scalar predicate ordering and all other key inputs match
- **THEN** they use one namespace-prefixed physical key rather than storing duplicate payloads

#### Scenario: Literal order is not an equivalence

- **WHEN** two find filters change field order inside a literal embedded document
- **THEN** the order-sensitive literal representations keep their physical keys distinct
