# Spec Delta

## ADDED Requirements

### Requirement: Proven top-level predicate order shares find identity

Both execution models SHALL give the same find-filter identity to permutations of supported top-level scalar equality predicates. The initial rule SHALL support plain dictionary filters with ordinary string field names and values of None or exact built-in bool, int, float, or str types, subject to existing key eligibility. It SHALL preserve type distinctions and leave the original filter unchanged for native execution.

#### Scenario: Reversed ordinary predicates hit one result

- **WHEN** a caller fully consumes and admits `find({"status": "active", "region": "eu"}, sort=[("_id", 1)])`, then consumes the same query with those top-level keys reversed
- **THEN** both synchronous and asyncio APIs return the cached documents without a MongoDB find or getMore command or duplicate resident payload

#### Scenario: A document or array value declines normalization

- **WHEN** a filter contains a document or array value and its top-level predicates are permuted
- **THEN** this rule declines normalization and the existing order-sensitive filter identity remains in use

#### Scenario: Numeric key distinctions remain intact

- **WHEN** filters differ in an equal-valued boolean, integer, floating-point, or BSON Int64 value that existing find keys distinguish
- **THEN** normalization retains those distinctions instead of merging identities

#### Scenario: Native execution receives the original filter

- **WHEN** a normalized query misses the cache
- **THEN** the MongoDB find command receives the caller's original predicate and value order, without an execution-time rewrite

### Requirement: Literal BSON ordering remains significant

Filter normalization SHALL preserve ordered document fields and array elements in literal values at every depth. It SHALL distinguish literal mappings from sequences and SHALL NOT recursively sort documents or reorder query operands.

#### Scenario: Embedded-document equality has an order counterexample

- **WHEN** raw MongoDB queries compare `metadata` against `{"a": 1, "b": 2}` and `{"b": 2, "a": 1}` in a fixture containing both document orders
- **THEN** their differing matches are demonstrated and the cached queries retain distinct identities and issue separate cold find commands

#### Scenario: A nested document or array is reordered

- **WHEN** a literal contains reordered nested fields, reordered documents within arrays, or changed array element order
- **THEN** normalization preserves the difference and no equivalence hit is created

### Requirement: Unproven filters retain their existing execution contract

Normalization SHALL decline filters outside the scalar predicate rule and preserve their existing order-sensitive key and eligibility behavior. Declining SHALL NOT reject an otherwise valid query or add a new bypass reason. Document and array values, operators, regexes, expressions, raw BSON, and custom values or mappings SHALL remain outside the rule. Implicit equality SHALL NOT be rewritten to `$eq`, and `$and` or `$or` operands SHALL NOT be reordered.

#### Scenario: An operator-bearing filter has reversed field order

- **WHEN** otherwise eligible filters containing comparison operators have their top-level keys reversed
- **THEN** this rule declines normalization and their existing distinct-key lookup behavior remains available

#### Scenario: Unsupported logical and expression forms are supplied

- **WHEN** a filter contains `$and`, `$or`, `$expr`, regexes, JavaScript, or other unsupported syntax
- **THEN** normalization preserves original syntax and operand order, with the existing cache or native-bypass path determining execution

#### Scenario: Scalar equality and explicit equality remain separate

- **WHEN** `{"a": 1}` is warm and `{"a": {"$eq": 1}}` is consumed with otherwise identical options
- **THEN** this change does not make those distinct forms share identity

#### Scenario: Malformed queries follow warming

- **WHEN** an invalid operator or malformed filter follows an admitted supported filter
- **THEN** it cannot reuse that supported identity and retains the applicable native error

### Requirement: Filter equivalence preserves every other read boundary

Equivalent-filter reuse SHALL retain namespace, projection, ordered sort, skip, limit, collation, codec profile, and all other cache-relevant read inputs. It SHALL retain eligibility, complete-consumption admission, mutation isolation, namespace-generation, and stream-availability contracts. Only find cursors SHALL gain this rule; other read methods SHALL retain their current filter representations.

#### Scenario: Another query input changes

- **WHEN** equivalent filters use different namespaces, projections, sorts, skips, limits, collations, or codec profiles
- **THEN** normalization alone does not make those query shapes share identity

#### Scenario: Unsupported read options follow warming

- **WHEN** an equivalent filter is used with an explicit session, batching, hint, or another unsupported cursor option
- **THEN** existing bypass behavior takes precedence over any equivalence hit

#### Scenario: A different read method uses equivalent filters

- **WHEN** a caller uses top-level permutations with find_one, counts, distinct, or an aggregation pipeline
- **THEN** this find-specific rule does not alter that method's cache identity or execution contract

### Requirement: Each equivalence rule has differential server evidence

Before an equivalence rule is enabled, differential tests SHALL compare its candidate forms through raw MongoDB on the project's supported integration fixture. Tests SHALL compare matching documents, ordering under an identical explicit sort, and relevant errors, with non-equivalence counterexamples. Concrete version-sensitive concerns SHALL require selected compatibility checks before enablement. Warm-hit tests SHALL verify actual command counts in both execution models.

#### Scenario: A candidate rule is evaluated

- **WHEN** top-level predicate-order normalization is introduced
- **THEN** raw-server differential cases precede enabling the rule, cover successful and empty results, and record exact tested server versions and error outcomes

#### Scenario: A transformation lacks evidence

- **WHEN** a candidate rule fails matching, sorted ordering, or relevant error comparison, or its required version runs are unavailable
- **THEN** that rule is not enabled on the strength of mocked tests or assumed equivalence
