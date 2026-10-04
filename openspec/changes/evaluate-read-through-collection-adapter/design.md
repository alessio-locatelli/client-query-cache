# Design

## Context

See [proposal.md](proposal.md) for motivation. The current views deliberately return lists for `find` and `aggregate`, expose no arbitrary PyMongo methods, and preserve a caller-owned client. [The navigation decision](../archive/2026-09-30-restore-pymongo-method-navigation/design.md) rejects PyMongo subtyping with incompatible cursor return contracts and large mirrored wrapper surfaces. The [examples friction log](../add-real-usage-examples/design.md#friction-log) identifies copied conversion code in three delivered integrations; Eve's feasibility work remains unfinished in that separate change.

`find` currently materializes before BSON admission sizing. The cache budget bounds retained encoded values, not the user's result list or peak fetching/serialization memory. Any cursor experiment must measure additional cache buffering independently of consumer-owned result retention.

## Goals / Non-Goals

**Goals:** Establish a driver-wide, evidence-backed compatibility contract and determine whether a typed adapter can cache useful reads without requiring application changes when caching is disabled. Give every public collection method and accepted argument combination an evidenced compatible path or a demonstrated rejection.

**Non-Goals:** A production adapter, published new API, changing existing list-returning methods, upstream repairs, completing Eve's example, Motor support, or claims about untested future driver releases. This study changes no behavioral specification and intentionally skips delta specs.

## Decisions

### D1. Inventory the driver contract before selecting experiments

Use the public `Collection` and `AsyncCollection` surfaces, including their public special methods and option-producing methods, as the inventory boundary. Include cursor protocols returned by those methods and the collection, database, client, and option properties needed to use the returned objects. Private driver internals are not a public compatibility promise; actual consumer dependence on them must still be reported.

Pin the minimum PyMongo version declared in `pyproject.toml`, the locked version, and the newest supported published release available when the study runs, deduplicating identical versions. Compare intervening released signatures and behavioral changes and exercise each distinct contract. Record MongoDB versions, topology, Python versions, and source URLs or immutable revisions. An open dependency lower bound does not justify claiming that future releases have been verified.

For each method, inventory positional and keyword arguments, defaults, variadic options, accepted value forms, validation, return protocols, side effects, and interacting options. Partition the infinite input space by behavior using released documentation and source: distinguish omission, explicit defaults, `None`, valid boundaries, malformed values, and interactions that change execution, validation, cache identity, or eligibility. Explain why each partition shares an execution path; exercise each distinct branch and interaction, with generated inputs for real invariants. Sampled calls or pairwise combinations alone do not establish full coverage.

Maintain a matrix mapping every method and partition to an experiment, source-based delegation argument, and one of the outcomes in D2. New or unclassified options must reach the native operation unchanged without cache lookup or admission; a warm entry must not cause an unknown option to be ignored. Directly forwarded families can share evidence only when their argument handling and native receiver are demonstrably unchanged. Document topology restrictions rather than conflating an unavailable fixture with unsupported behavior.

### D2. Require compatible execution or a demonstrated rejection for every case

Each matrix case must finish as compatible cached execution, compatible uncached forwarding, or a documented rejection. Forward writes, administration, session-bound reads, and other operations that cannot safely be cached. Infeasible cache admission is not infeasible operation compatibility. Investigate raw forwarding before rejecting any PyMongo-valid request; requiring the application to change a call to `.raw` is not compatible forwarding.

Run the same application function against raw PyMongo and the adapter with caching disabled, cold, warm, bypassed, and invalidated wherever those states apply. Change only construction or cache configuration, never the method calls, argument expressions, iteration, context management, or awaiting conventions. Exercise disabling caching between operations and during an active cursor's lifetime; disabled execution must neither serve nor admit cache entries.

Compare signatures, accepted arguments, returned values and protocols, sync/async call timing, error types and when they arise, side effects, ordering guarantees, decoding, read/write options, resource ownership, and static typing/source navigation. Cover invalid input after a valid warm query so cache hits cannot mask driver or server validation. Treat native network-dependent errors and observable server effects as contract questions requiring evidence; do not declare them compatible merely because a local return shape matches. Test both cursor construction and consumption failures.

Use the existing [cached-read safety requirements](../../specs/cached-read-api/spec.md) and [change-stream coherency requirements](../../specs/change-stream-coherency/spec.md) as the safety floor. Explain the existing eventual-freshness difference from uncached reads explicitly; it does not permit changing caller-selected options or claiming transactional, causal, or snapshot guarantees. Requests needing guarantees the cache cannot preserve must run natively. If a cache hit cannot preserve a required effect or error contract, demonstrate that boundary and select forwarding rather than weakening the contract silently.

For each rejection, retain a self-contained runnable prototype or minimal reproducible example with exact versions, setup/run commands, expected native behavior, observed incompatible behavior, and the violated requirement. Explain why direct forwarding and the alternative architectures in D3 cannot preserve that requirement under the stated constraints. A broken prototype, high maintenance cost, or a failed performance target is not proof that compatibility is infeasible. Limit conclusions to the demonstrated case and constraints. Environment blockers and untested cases remain unverified, not rejections or compatible outcomes.

### D3. Compare architectures using real prototypes

Compare the explicit read-view baseline, a composed collection/cursor adapter, and a cursor-preserving alternative whose type contracts genuinely match the driver. Build reusable native delegation and separate cache eligibility/admission from cursor execution. Reject a PyMongo subclass unless its inherited contract is preserved; reject casts or stubs that claim compatibility the runtime lacks. Preserve the caller's client and configured collection, without monkeypatching a shared client or temporarily replacing receivers around calls.

The prototypes must cover the six currently cache-aware methods (`find_one`, `find`, `aggregate`, `count_documents`, `estimated_document_count`, and `distinct`) and native delegation for the remaining inventory. `find_one` must retain native single-document calling and result behavior; `find` must return a cursor and preserve native sync/async construction timing; `aggregate` must preserve its own command-cursor contract. Investigate traversal and `with_options` so derived handles retain options and the intended cache policy. Test required concrete-type assumptions rather than hiding them behind annotations.

This study permits executable experiment files only in an untracked scratch directory under `/tmp`, using read-only imports of the working tree and disposable development fixtures. Commit reproducible experiment sources as report listings or links to immutable external artifacts, not production code. Every matrix row must lead to durable reproduction evidence; temporary paths, snippets omitting decisive logic, or references to conversational context are insufficient.

### D4. Stream immediately and publish only complete safe results

For a cache miss, finalize the query shape and capture namespace/availability generations before native execution. Yield documents as the native cursor produces them while retaining an isolated bounded candidate. Encode or copy candidate documents before yielding them so caller mutation cannot poison a later hit. Publish only after successful exhaustion of that exact query and a final check of the original guards. Preserve empty results and completed limited queries; never equate a consumed prefix with the complete unbounded query.

Investigate a hit cursor with the same declared protocol and method behavior as a miss cursor. Sorting, skip, limit, projection, collation, and other output-affecting options must determine the final cache key before lookup; a modified cursor cannot reuse the original query's entry. Exercise batch size, iteration, `to_list`, indexing/slicing, clone, rewind, explain, close, context cleanup, and the other public cursor operations discovered in D1. Neither a list iterator nor forwarding chain methods that escape the wrapper is sufficient evidence of cursor compatibility.

Exercise early exit, abandonment, garbage collection, timeout, iteration errors, cancellation, manager closure, cache disabling, writes during consumption, and stream continuity loss/recovery. Discard incomplete or invalidated candidates and release candidate resources; full consumption after invalidation cannot publish a stale result. Forward tailable, exhaust, partial-result, raw-batch, change-stream, session-bound, and other unsupported caching modes where native execution preserves the contract. Any rejection still requires D2 evidence.

Stop retaining a candidate once its encoded entry limit or shared candidate-buffer budget would be exceeded, release its retained data, and continue returning all native results. Investigate oversize single documents and multiple simultaneously active or abandoned cursors. Measure candidate allocations and encoding separately from driver batches and consumer accumulation; encoded-byte admission is not a strict process-memory bound. Evaluate avoidable per-document re-encoding, final-envelope copies, and eager whole-result decoding on cache hits.

### D5. Keep consumers as integration checks

Verify requests-cache 1.3.3, Celery 5.6.2, and py-abac 0.4.1 source revisions against the delivered integrations. Select a published Eve release or reuse the active examples change's verified selection. Map their reads, cursor calls, writes/admin operations, construction hooks, options, ownership, and concrete-type assumptions to D1 matrix rows. Exercise selected read conversions without copied upstream decoding/validation where feasible and attribute hits to library statistics rather than an upstream result cache.

These integrations test whether the adapter solves the original friction; they do not limit the driver inventory. Record consumer-specific or environment failures accurately and do not claim Eve compatibility without a working experiment. The other examples change retains ownership of its runnable Eve example; completing that example is not a prerequisite for the independent driver experiments.

### D6. Measure resource costs before recommending adoption

Before timing, record the execution paths, expected scaling, suspected bottlenecks, workloads, and any numerical adoption thresholds. Compare direct PyMongo, the materialized view, and viable prototypes with cold reads, hits, bypasses, writes racing reads, partial consumption, and oversized streams over several document counts/sizes and active-cursor counts. Record first-document and full-consumption latency, CPU, allocations/peak memory, network calls, and cache-hit evidence.

Use a streaming consumer for memory comparisons. Report how driver batches, candidate buffers, serialization, hit decoding, and consumer retention scale with result bytes and concurrency. Record measured rather than assumed bottlenecks, explain discrepancies, and compare improvements with maintenance and wrapper/signature costs across driver upgrades. Keep raw measurements untracked. Performance or maintenance concerns may justify declining adoption, but cannot justify labeling an operation incompatible.

### D7. Require a complete evidence report before closing the study

Write `docs/development/research/read-through-collection-adapter-evaluation.md` with D1's inventory and coverage rationale, D2's case outcomes and rejection demonstrations, D3's architectures and reproducible sources, D4's cursor traces, D5's integration results, and D6's concise measurements. This is an engineering report, not documentation of a published adapter.

Completion requires a disposition for every inventoried method and argument partition, preserved native behavior for compatible paths, a runnable demonstration for each rejection, truthful typing and ownership claims, and no admission of incomplete, mutated, or invalidated candidates. Unverified partitions or required topology experiments blocked by the environment prevent a claim of complete coverage; document the blocker rather than treating it as a no-go demonstration. Consumer-specific blockers must remain visible and limit consumer claims without substituting for driver evidence.

Record one adoption recommendation. A go identifies an independently implementable production contract, all evidenced exceptions, maintenance costs, and measured resource bounds. A no-go identifies whether the reason is a demonstrated incompatibility or an adoption trade-off; it cannot turn an unverified case or failed prototype into proof of infeasibility. Both require the complete driver disposition above. Either outcome leaves current runtime behavior intact and provides evidence for any subsequent production proposal, without adding production implementation tasks here.

## Risks / Trade-offs

- [The broader inventory becomes a second driver implementation] -> Reuse native delegation, justify behavioral partitions from released source, and measure maintenance without reducing coverage to consumer samples.
- [One failed prototype is mistaken for impossibility] -> Investigate forwarding and alternative architectures and restrict each rejection to a runnable demonstrated constraint.
- [Adapters preserve iteration but break chaining, errors, or async timing] -> Compare identical application functions in every applicable cache state and include positive/negative typing examples.
- [Memory evidence hides consumer retention or concurrent candidate growth] -> Separate allocations and measure shared candidate bounds with streaming consumers and multiple active cursors.
- [Topology or upstream problems masquerade as rejected operations] -> Keep unverified cases visible; document upstream defects with tracking URLs under AGENTS.md without repairing upstream or changing dependencies.
- [Scratch prototypes vanish] -> Retain complete decisive experiment sources and exact commands in the report; keep raw measurements untracked.

## Migration Plan

There is no runtime migration. The existing read-view design stays in effect throughout the study and after a no-go. The report is the completed artifact; any production adapter requires another explicit planning request based on its findings.
