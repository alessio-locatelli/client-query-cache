# Find filter normalization evidence

Historical evidence from `dfb1086a` in October 2026; the Python key-cost
measurements predate native key preparation. The current rule is maintained in
[the architecture guide](../../docs/development/architecture.md#cursor-driver-integration).

## Semantic boundary

The differential run used the project's disposable `mongo:8.0.4-noble` replica
set: MongoDB 8.0.4 and PyMongo 4.18.2, with both synchronous and asyncio clients.
Raw reads explicitly selected primary read preference and majority read concern.
The 38 initial cases passed before normalization was enabled.

Permuting top-level predicates preserved matching IDs and full documents under
identical `_id` sorting for boolean, integer, float, string, null/missing,
no-match, dotted-field, and explicit case-insensitive collation cases. Sorted
sequences were compared separately from unsorted matching ID sets.

Literal embedded-document field order, array element order, and document order
inside an array produced different matches: the forward literal selected `_id`
1000 and its reversed literal selected 1001. Comparison operators, logical
forms, regexes, and explicit equality retained their native successful outcomes.
Invalid top-level and field operators and constant division by zero raised
`pymongo.errors.OperationFailure` with server code 2 in either top-level order.
Native error text is not part of the equivalence contract.

MongoDB documents [implicit conjunction of comma-separated predicates](https://www.mongodb.com/docs/v8.0/reference/operator/query/and/)
and [order-sensitive document and array equality](https://www.mongodb.com/docs/v8.0/reference/operator/query/eq/).
The conjunction documentation also warns that expression errors need not
short-circuit. Together with the differential cases, this supports the chosen
flat scalar rule; it does not justify rewriting operator expressions.

The rule accepts only plain dictionaries with exact built-in string field names not starting
with `$`, and `None` or exact built-in bool, int, float, and str values. BSON
scalars, custom mappings/values, documents, arrays, regexes, expressions, and
operators retain ordered fallback. Existing key eligibility still applies,
including rejection of non-reflexive NaN keys. Other read methods are unchanged.
This is evidence for the tested versions, not an exhaustive server/driver
release matrix or a promise of deterministic unsorted output. No concrete
version-sensitive concern was found requiring a separate compatibility run.

Additional raw cases confirm scalar versus explicit `$eq` and reordered logical
operands can have the same native matches without sharing this find identity.
Implicit regex matching selected both string examples, whereas `$eq` with that
regex selected neither. The original 112-case file combined library regressions with one-off raw-server
experiments. Permanent tests retain cached-versus-native cases for scalar reuse,
ordered fallback, and native errors; the broader semantic matrix is historical
evidence, not an ongoing MongoDB regression suite.

## Recheck the semantic boundary

```bash
just pytest -n 0 -q tests/test_query_filter_normalization.py
```

These ongoing cached-versus-native regressions cover scalar reuse, ordered
fallback and native errors. They do not recreate the original broader raw-server
matrix or establish equivalence for untested MongoDB releases.
