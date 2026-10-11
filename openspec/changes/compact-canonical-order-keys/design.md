# Design

## Context

See [proposal.md](proposal.md#why) for motivation and [the delta specs](specs/) for the required behavior.

Cache keys are built in two passes. A builder in `src/client_query_cache/_core/order_sensitive_keys.py` turns mappings, sequences, doubles, and BSON Int64 values into 2-tuples tagged with private `_OrderTag` objects; `src/client_query_cache/_core/query_filters.py` wraps sorted scalar find filters in a third private tag, `_SCALAR_PREDICATES`. `canonicalize()` in `src/client_query_cache/_core/canonical.py` then tags bools, rejects unhashable and non-reflexive values, sorts unordered mappings, and passes through only 2-tuples tagged with its own three `_CanonicalTag` objects. It does not know the builder's tags, so it treats every builder node as a generic sequence: `(order-map, pairs)` becomes `(seq, (order-map, (seq, ((seq, pair), …))))`.

Canonical keys are re-fed into the builder and into `canonicalize()` on hot paths: the facade canonicalizes the generic `find_one` filter and read shape, then wraps both in `generic_find_one_discriminator()`; `CacheCore.lookup_find_encoded()` wraps the canonical family in `find_discriminator()` on every find lookup; and the shared-cache benchmark coordinator decodes canonical families from the wire before calling `FindReadShape.source`. Both functions recognize canonical subtrees in O(1) today, so wrapping copies nothing, and the new representation must keep that.

Throwaway prototype on CPython 3.14.7 (`tracemalloc` over 20,000 retained generic `find_one` discriminators built as the facade builds them; best of seven `timeit` rounds), current code against decisions 1–4:

| Filter                                        | Key tuples | Bytes per key | Build CPU per key |
| --------------------------------------------- | ---------: | ------------: | ----------------: |
| `{"code": <str>}`                             |     10 → 4 |     649 → 273 |     10.1 → 5.1 µs |
| `{"code": <str>, "state": {"$in": [48 str]}}` |     22 → 8 |   1,785 → 913 |    63.0 → 51.8 µs |

With per-field pair tuples instead of decision 4, the same prototype kept 5 and 11 tuples (329 and 1,081 bytes) at the same CPU.

## Goals / Non-Goals

**Goals:**

- Each private key tag appears once per node in canonical keys, and payloads are canonicalized in place.
- Re-canonicalization stays O(1) for canonical subtrees, without allocation.

**Non-Goals:**

- Building keys in one pass or removing the facade's repeated canonicalization of the same discriminator; see decision 1, alternative B, and [issue #248](https://github.com/alessio-locatelli/client-query-cache/issues/248).
- Changing the unordered canonical mapping, which keeps sorted pair tuples; it only appears in rarely retained keys such as collations in alias keys.

## Decisions

### 1. Builder tags map to distinct canonical tags

Each builder tag carries a canonical counterpart. `canonicalize()` converts a builder node `(builder_tag, payload)` into `(builder_tag.canonical, canonical payload)` and returns any 2-tuple tagged with a canonical tag unchanged. The builder passes through nodes carrying either kind of tag, as it passes through canonical nodes today.

| Alternative                                                                                   | Pros                                                                            | Cons                                                                                                                                                                                                                                                                   |
| --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A. Distinct builder and canonical tags (chosen)                                               | O(1) passthrough of canonical subtrees; changes confined to the two key modules | Two passes over each input remain                                                                                                                                                                                                                                      |
| B. Builder emits canonical output directly, tagging bools and rejecting invalid values itself | One pass and one set of allocations                                             | The builder starts raising `UnsupportedCacheRequestError`; `record_write()`, find cursors, `aggregate()`, `distinct()`, and `count_documents()` build raw discriminators before bypass classification, so each call site and the bypass-reason precedence would change |
| C. One tag per node kind for both forms, canonicalizing the payload on every call             | Fewest tag objects                                                              | A canonical node cannot be told apart from a raw one, so re-canonicalization walks and validates the whole subtree; every find lookup and generic `find_one` discriminator would walk its filter twice                                                                 |

Unknown for B: how much CPU a single pass saves beyond A, which needs its own prototype. B overlaps with the facade's repeated canonicalization, so [issue #248](https://github.com/alessio-locatelli/client-query-cache/issues/248) tracks both. No further work is needed for C.

### 2. `canonical.py` owns the tag mechanism, builders own their tags

`canonical.py` defines a pending-tag type next to `_CanonicalTag`. Each pending tag holds its canonical counterpart, created from a name used in its `repr`, and a payload kind: an item tuple whose items are canonicalized one by one, or one value canonicalized as a whole. `order_sensitive_keys.py` creates its mapping and sequence tags with item payloads and its float and Int64 tags with single values; `query_filters.py` creates `_SCALAR_PREDICATES` with a single value, its ordered mapping node, which removes the generic-sequence layer that tag adds to every scalar find filter today. Dependencies keep their current direction.

| Alternative                                            | Pros                                 | Cons                                                                                                |
| ------------------------------------------------------ | ------------------------------------ | --------------------------------------------------------------------------------------------------- |
| Pending-tag type in `canonical.py` (chosen)            | No import cycle; one conversion rule | One small class                                                                                     |
| Define every builder tag in `canonical.py`             | No new type                          | `canonical.py` learns order-sensitive and filter semantics, and tag ownership splits across modules |
| New shared `_core/key_tags.py` module                  | Neutral home                         | A third module for two classes; `canonicalize()` still needs a per-tag conversion table             |
| Registration table that builder modules fill at import | `canonical.py` names no builder      | Mutable global state whose content depends on import order                                          |

Conclusion: no follow-up needed.

### 3. Tags are recognized by type

Both `canonicalize()` and the builder test `type(value[0])` against `_CanonicalTag` and the pending-tag type instead of scanning `_OWN_TAGS` tuples, which are removed. The check is O(1), avoids a generator on every 2-tuple (sort specifications are 2-tuples), and needs no update when tags are added. Instances of both types exist only as private module constants, so caller data cannot carry one; the existing forged-tag tests continue to cover strings that imitate tag names. The alternative, identity scans over a tuple of seven or more tags, has no advantage. Conclusion: no follow-up needed.

### 4. Ordered mappings use one flat payload

An ordered mapping's payload alternates canonical field names and values, `(<canonical:ordered-map>, ("code", "C0000001", "state", …))`, so ordered mappings and sequences share the item-tuple payload kind. Equality is unchanged because every field occupies two fixed positions. Per-field pair tuples would follow the issue's sketch and match the unordered mapping, but they keep one tuple per field, worth 56 and 168 bytes per key in the prototype at equal CPU. No consumer reads the builder's mapping payload outside `canonical.py`. Conclusion: no follow-up needed.

### 5. A frozen copy of the previous algorithm is the equality oracle

A test helper keeps a self-contained copy of the previous builder and `canonicalize()`, with their own tags. The property test from the [property-based-testing delta](specs/property-based-testing/spec.md) keys each generated input through both implementations and compares which inputs collide. A differential oracle checks the exact claim the [cache-core delta](specs/cache-core/spec.md) makes, while invariant-only tests (idempotence, order sensitivity) cannot detect a merged or split equality class. The helper stays as a regression oracle and receives no tests of its own. Conclusion: no follow-up needed.

### 6. Shared-cache wire names point at canonical tags

`benchmarks/stream_cost/shared_cache/wire.py` keeps its tag names but maps the order and scalar-predicate names to the canonical counterparts, and drops builder tags, which cannot occur in canonical keys. `PROTOCOL_VERSION` stays 1: the coordinator and its workers always run from one checkout, and keys are never persisted. Bumping it would only change test fixtures. Conclusion: no follow-up needed.

### 7. Measurements

Key cost is measured without MongoDB by a benchmark test that retains 20,000 generic `find_one` discriminators for each issue filter and prints `tracemalloc` bytes and tuples per key and build CPU, so the report gains a reproduction command for the key row of its per-entry attribution. End-to-end memory reruns only the process-memory scenarios whose keys change (`small-entries`, `large-keys`, `cycles`). `documents` reuses one shared default read shape per collection, and `result-sets` holds 68 entries, so neither changes measurably. The report's current figures serve as the baseline because `src/` did not change between their measurement (`2e714e6`) and this change's base (`9fbcd04`).

Resource profile of a key build after the change, for an input with n nodes:

```text
facade filter
  -> builder pass            O(n) CPU, transient builder tuples
  -> canonicalize pass       O(n) CPU, retained canonical tuples (about half of today)
  -> discriminator wrapper   O(1) per canonical subtree, no copy
lookup
  -> dict probe              hash of a key tree with about half the tuples
```

The expected bottleneck stays the two passes over large filters: their work grows with the number of values, as the prototype's 51.8 µs for the 48-value filter against 5.1 µs for one field shows.

## Risks / Trade-offs

- [A missed conversion path merges or splits an equality class] → The differential property test covers unordered, order-sensitive, discriminator, scalar-filter, and nested-subtree builders, plus NaN and unhashable rejection parity.
- [Raw and decoded families hash differently and break limit compatibility] → Tests compare `FindReadShape.source` and keys for raw, canonical, and wire-decoded families.
- [Process-memory figures in public guidance become stale] → The rerun updates the report, deployment guide, and `context7.json` rule together.
- [Keys are less readable when debugging] → Canonical tags keep descriptive `repr` names, so a key still prints its node kinds.

## Migration Plan

Keys live only in process memory and are rebuilt on every read, so a new release needs no migration or cache flush. Rollback is a revert.
