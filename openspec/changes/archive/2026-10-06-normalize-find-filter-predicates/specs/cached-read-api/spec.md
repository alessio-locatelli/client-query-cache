# Spec Delta

## ADDED Requirements

### Requirement: Top-level scalar predicate order shares find identity

Both execution models SHALL share find identity across permutations of plain dictionaries with exact built-in string fields not starting with `$` and values of None or exact built-in bool, int, float, or str types, subject to existing key eligibility and type distinctions. Unsupported forms SHALL retain ordered identity and existing eligibility. Normalization SHALL leave native filters and other key dimensions unchanged and SHALL apply only to find cursors.

#### Scenario: Scalar predicates are reversed

- **WHEN** a fully consumed find query is repeated with supported scalar predicates in a different top-level order and otherwise identical inputs
- **THEN** the cached result is reused without a find/getMore command or duplicate resident payload

#### Scenario: A filter contains a document, array, or operator

- **WHEN** an otherwise cache-eligible filter falls outside the scalar rule
- **THEN** it remains cacheable by its ordered shape, and reordering it does not create an equivalence hit

#### Scenario: A normalized query misses

- **WHEN** a supported scalar filter is executed on a cache miss
- **THEN** native execution receives the caller's original filter order

#### Scenario: Another query input differs

- **WHEN** a read changes another output-affecting key input
- **THEN** normalization preserves that distinction and existing compatible-limit rules
