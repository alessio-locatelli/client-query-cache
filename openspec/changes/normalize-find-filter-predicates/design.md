# Design

## Context

See [proposal.md](proposal.md) for motivation. Both native find cursor subclasses construct their discriminator in `_prepare()` from the final cursor fields. `order_sensitive_discriminator_key()` preserves mapping/sequence order and distinguishes floats and BSON Int64 from ordinary integers. `canonicalize()` alone sorts mappings, so passing a raw filter to it would erase literal BSON ordering. Neither utility is a semantic query parser.

The existing sync/async `cursors` fixture records actual read commands and uses a disposable MongoDB replica set, currently `mongo:8.0.4-noble`. Reuse that fixture. This proposal records intended verification, not an existing differential result.

## Goals / Non-Goals

**Goals:** One small scalar-predicate equivalence rule, one shared key helper, unchanged fallback, and real-server evidence before enabling the rule.

**Non-Goals:** Recursive syntax or BSON classification, an operator registry, a planner, runtime equivalence queries, new test-runner interfaces, or changes to find_one/counts/distinct/aggregation. Native query documents are never rewritten.

## Decisions

### 1. Normalize only top-level scalar equality predicates

Support plain `dict` filters whose keys are strings not beginning with `$` and whose values are `None` or exact built-in `bool`, `int`, `float`, or `str` instances. Sort only those top-level field names for cache identity. Do not coerce values or validate MongoDB field-path syntax. Existing native validation and key eligibility still decide whether the query can execute or be cached; for example, non-reflexive NaN values retain the existing uncanonicalizable-key bypass.

Any mapping or sequence value, operator form, regex, BSON-specific scalar, custom subclass, raw BSON, or non-plain mapping declines the whole normalization rule. Return the existing order-sensitive representation on decline. There is no nested semantic traversal: embedded document and array ordering is preserved by the existing fallback. Empty and single-field plain filters follow the same boundary without introducing additional equivalence rules.

MongoDB documents [implicit AND](https://www.mongodb.com/docs/v8.0/reference/operator/query/and/) for comma-separated predicates. Permuting ordinary scalar equality predicates leaves their conjunction unchanged. Its [document and array equality guidance](https://www.mongodb.com/docs/v8.0/reference/operator/query/eq/) explains why literal ordering must survive fallback. These sources justify the selected boundary; task 1.1 verifies matching, deterministic sorted output, and relevant errors against the real server. Operator expressions stay excluded because [AND error handling](https://www.mongodb.com/docs/v8.0/reference/operator/query/and/#behavior) does not promise short-circuit evaluation.

| Alternative                              | Benefits                                                                                | Costs, unknowns, and conclusion                                                                                 |
| ---------------------------------------- | --------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Scalar predicate rule, chosen            | Flat eligibility check; satisfies the acceptance example; no nested semantic classifier | Fewer normalized filters. Server matching/error evidence remains to be established in task 1.1.                 |
| Sort top-level keys regardless of syntax | Minimal checking                                                                        | Shares uncertain operator/expression forms without their own proof. Reject; no further research is needed.      |
| Normalize all read methods               | Broader reuse                                                                           | Expands unrelated contracts and proof requirements. Reject as outside find scope; no research is required here. |

### 2. Change only the executed find key's filter component

Create `_core/query_filters.py` with one shared helper. A supported filter produces a private tagged representation of sorted top-level `(field, value-key)` pairs, with values represented by the existing order-sensitive discriminator utility. A declined filter produces exactly its existing ordered representation. The normalized tag keeps supported identities separate from uncertain fallback forms; verify the complete discriminator wrapping and `canonicalize()` path rather than only comparing intermediate Python values.

Both find preparation paths obtain the helper's representation at execution time from the final native `_spec`. Use it consistently for lookup and `CursorCapture` admission, preserving every other executed key component and leaving `_spec` untouched. Eligibility classification still examines the original filter. A decline adds no bypass reason or error: otherwise eligible unsupported filters remain cacheable by exact shape, and existing ineligible queries retain native execution.

This change has no prerequisite on another planned feature. Both plans use identical operation-neutral wording for the shared cache-core requirement, and their feature-specific scenarios belong to separate added requirements.

| Alternative                                                      | Benefits                                                                           | Costs, unknowns, and conclusion                                                                |
| ---------------------------------------------------------------- | ---------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| Shared filter-key helper at the executed filter boundary, chosen | Same behavior in both APIs; independent scope; reuses ordered value representation | Tagged-key composition is verified in tasks 2.1 and 2.2; no separate research is needed.       |
| Change generic canonicalization                                  | Automatically changes existing callers                                             | Erases literal or unrelated read-key distinctions. Reject; no research is needed.              |
| Rewrite the native filter or add equivalence aliases             | Aligns remote spelling or retains original physical identities                     | Changes execution or introduces an unnecessary ownership index. Reject; no research is needed. |

### 3. Use focused real-server differential tests

Add raw-server cases to `tests/test_query_filter_normalization.py` before integrating normalization. Use the existing supported fixture and primary/majority semantics. Compare matching IDs without assuming unsorted order, and compare full documents under identical `_id` sorting. Cover each supported scalar type, null/missing fields, empty results, ordinary dotted fields, and supported explicit collation. Task 1.1 records exact MongoDB and PyMongo versions, outcomes, semantic justification, and exclusions in `reports/query-filter-normalization/summary.md`; task 4.2 extends that report with performance evidence.

Keep counterexamples for reordered embedded-document fields, nested documents and arrays, scalar versus `$eq`, logical operand order, regex versus explicit equality, and error-producing expressions. Document-valued and array-valued filters decline as a whole, even when only their top-level predicate order changes. Unsupported malformed/operator cases retain native exception class and server code where defined; error text need not be identical when native order legitimately selects a different error. Warm-hit tests then prove actual command counts, fallback hits, and unchanged cold native arguments in both execution models.

Dedicated regression cases cover the changed filter-key boundary: supported permutations, ordered fallback, native arguments, and separation from other query inputs. Existing cursor tests cover lifecycle and mutation isolation; this change does not add reordered-filter variants of those tests.

Run the focused file with `just pytest -n 0 tests/test_query_filter_normalization.py`. Do not add a global image option, exhaustive released-version inventory, CI matrix, or server-management harness. An observed or documented version-sensitive concern requires a selected disposable compatibility experiment and its recorded outcome before enabling the rule. Such an experiment reuses the tests and an isolated temporary checkout of the existing fixture, without adding a permanent runner interface. No concrete version-sensitive concern is established at planning time; version selection is therefore not an open mandatory task. A failed or unavailable required differential run is a visible blocker.

| Alternative                                                            | Benefits                                                               | Costs, unknowns, and conclusion                                                                                                   |
| ---------------------------------------------------------------------- | ---------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| Existing fixture plus concern-driven compatibility experiments, chosen | Reuses normal lifecycle and command monitoring; no new runner contract | Evidence applies to tested versions. Task 1.1 establishes it; concrete compatibility concerns must be resolved before enablement. |
| Documentation or mocks alone                                           | Fast                                                                   | Does not establish real-server matching/order/error behavior. Reject; no research is needed.                                      |
| Full-suite version matrix or custom harness                            | Broad validation or isolated orchestration                             | Duplicates unrelated execution or existing container lifecycle. Reject; no research is needed.                                    |

### 4. Measure the bounded rule's cost

For `p` top-level predicates, the new eligibility check costs O(p), sorting costs O(p log p), and normalized representation allocation costs O(p). A declined filter uses the existing generic ordered representation, including its existing nested traversal; the new helper adds no recursive semantic classification. Key construction adds no remote calls or resident equivalence index. Hits retain the existing result-decoding cost.

Use Hypothesis over supported scalar predicate permutations, and focused fallback cases for nested-order/type distinctions. Tasks 1.2, 4.1, and 4.2 capture baseline/post-change latency, key-construction CPU/allocations, commands, and resident bytes using existing cursor benchmark conventions. Retain only the concise Markdown report and reproduction commands; raw output remains untracked. No numeric speedup or measured bottleneck is claimed at proposal time.

## Risks / Trade-offs

- [Some safe filters remain unnormalized] → Accept this limit to avoid a nested classifier; they retain their existing exact cache behavior.
- [Supported and fallback representations collide or lose types] → Use existing value tags and a private normalized tag; task 2.2 verifies the full key pipeline and BSON-specific fallback distinctions.
- [Fallback changes query execution or eligibility] → Leave the original filter and classification intact; tasks 3.1 and 3.2 prove repeated exact fallback hits and native errors.
- [Unsorted output is interpreted as stable order] → Compare exact sequences only under an explicit deterministic sort; preserve the existing ordering contract.
- [A compatibility issue appears on another supported version] → Require a selected disposable experiment and resolve the concern before enabling the affected rule; document tested versions without claiming exhaustive future coverage.

## Migration Plan

Cache state is process-local; there is no persisted key migration. Add raw differential cases first, then the helper and sync/async integrations, then current public guidance. Do not add key-version compatibility branches or a toggle. Reverting helper integration restores ordered exact keys for future managers. Archive only after implementation, measurements, and review are complete.
