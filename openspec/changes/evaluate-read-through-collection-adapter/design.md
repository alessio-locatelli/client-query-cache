# Design

## Context

See [proposal.md](proposal.md) for motivation. The current views deliberately return lists for `find` and `aggregate`, expose no arbitrary PyMongo methods, and preserve a caller-owned client. [The navigation decision](../archive/2026-09-30-restore-pymongo-method-navigation/design.md) rejects PyMongo subtyping with incompatible cursor return contracts and large mirrored wrapper surfaces. The [examples friction log](../add-real-usage-examples/design.md#friction-log) identifies copied conversion code in three delivered integrations; Eve's feasibility work remains unfinished in that separate change.

`find` currently materializes before BSON admission sizing. The cache budget bounds retained encoded values, not the user's result list or peak fetching/serialization memory. Any cursor experiment must measure additional cache buffering independently of consumer-owned result retention.

## Goals / Non-Goals

**Goals:** Decide whether a useful, typed opt-in adapter can eliminate copied conversion code while preserving the consumer's required collection/cursor behavior and bounded additional memory.

**Non-Goals:** A production adapter, published new API, changing existing list-returning methods, upstream repairs, completing Eve's example, Motor support, or claiming universal PyMongo compatibility. This study changes no behavioral specification and intentionally skips delta specs.

## Decisions

### D1. Use versioned consumer requirements rather than a generic proxy promise

Start with the delivered requests-cache 1.3.3, Celery 5.6.2 and py-abac 0.4.1 integrations and their pinned source revisions in the examples design. Verify the installed release/source boundary again for the experiments. Select a published Eve release and record its compatibility; if the active examples change has a verified selection, reuse it rather than duplicating work. Record a source/dependency blocker explicitly where a consumer cannot run in the supported environment.

For each consumer, enumerate exact reads, cursor operations, writes/admin methods, option-producing calls, client ownership, receiver construction and concrete-type assumptions. Measure how much upstream conversion must still be copied after an adapter is introduced. Merely caching a method while retaining all conversion overrides is not a successful result.

### D2. Compare three architectures in isolated experiments

Compare the current explicit read view, a composed adapter with a bounded declared collection/cursor protocol, and a cursor-preserving alternative whose type contracts genuinely match the driver. Reject a PyMongo subclass unless its complete inherited contract is preserved; reject casts/stubs that claim compatibility the runtime lacks. Do not monkeypatch a shared client or temporarily switch a storage receiver around a call.

Build only the smallest surfaces needed to test these consumers. For sync/async, audit method timing as well as returned types: native async `find` constructs a cursor without awaiting, while native async aggregation has its own driver contract. An adapter must not require an upstream consumer to adopt the existing awaited-list `find` contract. Required unsupported behavior must either return an ordinary raw cursor with truthful typing or produce a no-go result; do not hide a correctness limitation behind an undocumented fallback.

This study permits code only in an untracked scratch directory under `/tmp`, using read-only imports of the working tree. The report contains source excerpts only when needed to explain the decision. Retain a small reproducible experiment script in the report as a fenced listing or a linked immutable external artifact; do not claim an untracked temporary path is a durable reproduction source. Production code and public examples stay unchanged.

### D3. Test cursor state and bounded buffering before claiming compatibility

Cover consumer-required sort/skip/limit/projection, batch size, iteration/to-list, close/context cleanup, clone/rewind where used, abandonment, unsupported cursor modes, errors during iteration, and a write racing cursor consumption. Track the original query's namespace/availability generations across execution and consumption. Admit only a complete result that still passes the shared guards. Full consumption after an invalidation must not publish a stale result.

Measure a bounded accumulation design that stops retaining cache candidates after its encoded byte limit is exceeded while continuing to stream the complete result. Include oversized single documents and buffering/encoding allocations; an admission-byte budget is not automatically a strict process-memory bound. Discard partial candidates on close, error, cancellation or abandonment. Evaluate whether re-encoding per document or building the final BSON envelope creates avoidable duplicate work. Distinguish driver's batch memory, consumer-retained output and extra cache-candidate memory in the report.

### D4. Decision gates and durable report

Write `docs/read-through-collection-adapter-evaluation.md` with the compatibility matrix, pinned sources, reproducible setup/run commands, architecture comparison, measurements, and a go/no-go decision. This is an engineering report; it does not publish proposed usage as current library functionality.

A go requires verified behavior and truthful tooling for each delivered consumer's selected read paths, preservation of raw writes and ownership, bounded additional cache buffering, no admission of incomplete/stale results, equivalent native execution models, and a precisely bounded support contract. Eve is a stress case: document unsupported requirements or an environment blocker and explicitly limit any recommendation; do not claim Eve compatibility without a working experiment. The report must enumerate wrapper/signature maintenance across driver upgrades, not just runtime latency.

A no-go identifies the failed gate and recommends retaining explicit views. Either decision completes this study. A go does not start production work; it supplies the contract and measurements for a separately authorized implementation proposal. Other pending changes are not required to finish this comparison.

### D5. Resource measurements

Use cold reads, repeated hits, writes racing reads, partial consumption and oversized result streams at several document counts/sizes. Compare direct PyMongo, the current materialized view, and viable experiments. Record network calls, first-item/full-consumption latency, CPU, allocation/peak-memory behavior and cache hit evidence. Use a streaming consumer for memory comparisons so consumer accumulation does not dominate extra buffering. Report how costs scale with result bytes, active cursors and driver batches, including the suspected and measured bottlenecks. Keep raw results untracked.

## Risks / Trade-offs

- [The experiment becomes a second driver implementation] -> Stop at the declared consumer contract and report inherited or unsupported behavior honestly; include upgrade maintenance as a gate.
- [Adapters preserve iteration but break cursor chaining or async call timing] -> Test actual consumer calls and positive/negative type-check examples, not only `list(cursor)`.
- [Performance evidence hides buffering in the consumer] -> Separate driver, consumer and cache-candidate memory and use streaming workloads.
- [Upstream dependency defects consume scope] -> Record incompatibilities without repairing upstream or altering project dependencies.
- [Scratch prototypes vanish and make the report irreproducible] -> Embed the minimal experiment sources and exact commands in the durable report; retain no raw benchmark payloads.

## Migration Plan

There is no runtime migration. The existing read-view design stays in effect throughout the study and after a no-go. The report is the completed artifact; any production adapter requires another explicit planning request based on its findings.
