# Find filter normalization evidence

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

## Implementation measurements

The one-off baseline and final runs each passed the then-current 122-case
cursor benchmark file. The experimental workloads used 240 small documents, 2/8/32 scalar predicates,
and document/array/operator fallback sizes of 4/64 elements. Each phase clears
the namespace and repeats ten times. End-to-end latency is the median of the
last nine repetitions, including cursor construction and materialization.
Key CPU is the median of ten batches of 100 shape-plus-canonicalization calls;
key allocation is the peak traced heap for one separate call. The table averages
the synchronous and asyncio summaries (key CPU also averages the three phases); times are microseconds, heap is bytes.

| Predicates | Cold baseline → final | Exact hit baseline → final | Reversed baseline → final | Key CPU baseline → final | Key heap baseline → final |
| ---------- | --------------------- | -------------------------- | ------------------------- | ------------------------ | ------------------------- |
| 2          | 1713.7 → 1825.6       | 228.2 → 236.2              | 1423.8 → 232.4            | 21.6 → 26.3              | 2776 → 3752               |
| 8          | 1961.2 → 1990.3       | 255.8 → 270.0              | 1494.0 → 269.2            | 36.0 → 42.5              | 2808 → 3784               |
| 32         | 2507.8 → 2697.7       | 370.1 → 386.3              | 2057.4 → 386.8            | 95.7 → 105.5             | 3324 → 4280               |

Every reversed scalar read changed from one `find` plus one `getMore` to zero
read commands. The baseline retained two payloads (32,446 BSON bytes); the
final run retained one (16,223 bytes), with one additional hit and no duplicate
admission. Repeated exact filters also issued zero read commands. The BSON
resident budget excludes Python query keys and existing family-index overhead;
the heap column describes transient key construction, not total manager memory.

For reversed fallback workloads, the medians across APIs, predicate counts,
and nested sizes were:

| Form     | Latency baseline → final | Key CPU baseline → final | Key heap baseline → final |
| -------- | ------------------------ | ------------------------ | ------------------------- |
| Document | 1254.2 → 1229.9          | 146.0 → 148.4            | 4760 → 4760               |
| Array    | 790.9 → 872.0            | 70.2 → 71.5              | 4368 → 4368               |
| Operator | 1065.2 → 1004.5          | 74.9 → 76.3              | 5752 → 5752               |

Fallback permutations still sent one cold `find`, stored a separate payload,
and subsequently hit their repeated exact shape. Their nested traversal belongs
to the existing ordered-key utility. The helper adds only a flat eligibility
check; it introduces no remote lookup calls or additional resident index.

A first normalized representation nearly doubled scalar key CPU at 32
predicates by rebuilding tuple-pair structure during outer wrapping. Reusing
the utility's already-tagged ordered mapping after a shallow sort removed that
avoidable work. The final rule adds about 5–10 microseconds of key CPU and about
1 KiB of traced peak heap in these workloads. Exact hits are slightly slower;
reversed reads avoid server execution and duplicate payload storage. Cold
latencies vary, and this run does not establish a cold-read speed improvement.
These are local measurements, not universal performance guarantees.

A `cProfile` run of 10,000 32-predicate key constructions shows generic
canonicalization and type checks dominate pure key work; sorting is not among
the top twelve functions by internal time. The profile is instrumented and its
timings are not compared with the unprofiled CPU numbers. Remote execution and
result capture remain the main observed difference between cold and warm reads;
the key cost accounts for roughly a quarter of final 32-predicate hit latency.

## Ongoing checks

```bash
just pytest -n 0 -q -s tests/test_query_filter_normalization.py
just pytest -n 0 -m benchmark -q -s tests/benchmark/test_cached_read_cursors.py -k scalar_filter_key_cost
```

Raw command output and measurements remain untracked outside the repository.

These commands run the focused library regressions and the representative
scalar key benchmark. They do not recreate the historical semantic or
end-to-end performance matrices above. Those experiments used the workloads
and measurement procedure described in this report. The original latency,
allocation, command, and resident-byte figures remain implementation evidence;
the ongoing benchmark reports only key CPU for exact and permuted filters.

Reproduce the standalone key profile with:

```python
import cProfile
import pstats

from client_query_cache._core.canonical import canonicalize
from client_query_cache._core.find_reads import find_read_shape

predicates = {f"absent-{index}": None for index in range(32)}
profiler = cProfile.Profile()
profiler.enable()
for _ in range(10_000):
    shape = find_read_shape(
        predicates, None, {"_id": 1}, 0, 0, collation=None, codec=None
    )
    canonicalize(shape.discriminator)
profiler.disable()
pstats.Stats(profiler).sort_stats("tottime").print_stats(12)
```
