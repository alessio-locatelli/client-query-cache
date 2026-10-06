# Design

## Filter identity

Both native cursor APIs pass the final `_spec` into the shared
`find_read_shape()` builder. Only plain dictionaries with exact built-in string
fields not beginning with `$` and `None` or exact built-in bool, int, float, or
str values qualify for normalization. Empty and single-field dictionaries use
the same rule. Native field validation and existing key eligibility still apply,
including the uncanonicalizable-key bypass for NaN.

`find_filter_key()` shallowly sorts qualifying dictionaries, adds a private tag,
and reuses the existing ordered-key utility. The tag prevents collisions with
fallback identities; the utility preserves numeric type distinctions. All other
forms retain their existing ordered representation and eligibility. There is no
nested semantic classification or native filter rewrite.

Lookup, capture admission, and existing limit-family membership use the same
representation. Other key dimensions and read methods are unchanged. Cache
state is process-local, so there is no persisted-key migration.

## Evidence and ongoing checks

The semantic and broad performance matrices were one-off implementation
experiments. Their tested versions, outcomes, measurements, and limits are
recorded in `reports/query-filter-normalization/summary.md`.
They do not become a permanent MongoDB regression suite or a general requirement
on future equivalence rules.

Permanent integration cases compare cached reads with native reads and verify
command counts, one-payload reuse, ordered fallback, and native errors without
fixed server codes. Core property tests cover scalar permutations and fallback
representations. Existing cursor tests cover other query inputs and lifecycle.
The ongoing benchmark measures exact and permuted scalar key construction for
small and larger filters, using the builder shared by both APIs.

## Cost

For `p` predicates, eligibility costs O(p), sorting O(p log p), and normalized
representation allocation O(p). Fallback retains the ordered utility's existing
nested traversal. No remote lookup, alias index, or additional resident payload
is added. Hits retain the existing decoding cost. The report records measured
key overhead and the savings when a permuted query can reuse a cached result.
