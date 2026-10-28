# process-local-cache-evaluation Specification

## Purpose

Evaluate and integrate native process-local cache storage through representative application reads, retaining qualifying implementations in the same change on comparable correctness, runtime, and memory evidence.

## Requirements

### Requirement: Candidate selection is private and explicit

The evaluation SHALL select the reference or native candidate before manager creation in an isolated process, without adding a public backend option. A retained native core SHALL be used by ordinary process-local construction. Setup failure SHALL be visible rather than silently selecting the reference.

#### Scenario: A normal application creates a manager

- **WHEN** an application uses the qualified default distribution build
- **THEN** it receives the native process-local implementation through the existing manager API without selecting a backend

#### Scenario: Experimental setup fails

- **WHEN** a native evaluation process cannot load its selected core
- **THEN** the evaluation reports failure and does not record reference execution as native execution

### Requirement: Evaluated cores satisfy the existing read contract

The evaluation SHALL compare both cores against the existing cache-core, cached-read-api, and change-stream-coherency requirements. It SHALL exercise both execution models, all supported read methods, custom codecs, document classes, and bypass/error behavior. An unsupported or divergent case SHALL block native retention.

#### Scenario: A custom codec or session changes read behavior

- **WHEN** a conformance case uses application decoding or a session-bound operation
- **THEN** both cores preserve the specified result, error, cache outcome, and caller-owned resource behavior

### Requirement: Key equivalence is preserved across native ownership

Experimental keys SHALL preserve the reference's equality and distinctions, including identity numeric equivalence, discriminator numeric subtypes, field order, collation, namespace, and read shape. Hash collisions SHALL NOT establish equality. Python values without a native representation SHALL NOT silently become misses or additional bypasses.

#### Scenario: Similar keys have different meanings

- **WHEN** two supported discriminators differ only in a type or ordering that the reference distinguishes
- **THEN** neither reads the other's cached value

#### Scenario: A supported leaf requires Python equality

- **WHEN** a supported key contains a value without a compact native representation
- **THEN** the experiment preserves reference key behavior and accounts for its retained Python resources

### Requirement: Native ownership preserves ordering and reclamation

The evaluation SHALL verify generation-fenced admission and lookup, alias ownership, exact replacement cleanup, compatible find sources, eviction, availability transitions, namespace release/recreation, and close. Operation-ordering and concurrent cases SHALL reject stale observations and reclaim obsolete native and Python references under the existing contracts.

#### Scenario: A delayed admission crosses namespace recreation

- **WHEN** an old capture completes after its namespace is dropped and recreated
- **THEN** the candidate is rejected without affecting newer entries or aliases

#### Scenario: A cursor outlives its manager

- **WHEN** a started hit remains reachable after the manager closes
- **THEN** its owned result stays usable and later cleanup does not access released storage

### Requirement: Opaque equality uses a revalidated candidate version

Python key callbacks SHALL run outside native critical sections. A lookup SHALL commit its validity decision, LRU update, and outcome only against the candidate version compared outside the lock, with concurrent insertion, invalidation, replacement, and reentrant mutation detected. A callback exception SHALL propagate without committing that lookup's pending side effects.

#### Scenario: Equality reenters and replaces the candidate

- **WHEN** a colliding key's equality callback replaces or invalidates the compared entry before returning
- **THEN** lookup revalidates and retries rather than returning bytes or updating LRU/statistics for the obsolete candidate

#### Scenario: Equality raises after a concurrent mutation

- **WHEN** a Python equality callback raises while another operation changes the bucket
- **THEN** the exception propagates, the concurrent operation remains intact, and the interrupted lookup commits no pending cache outcome

### Requirement: Workloads and decision rules precede candidate measurements

The evaluation SHALL register immutable revision identities, hypotheses, target workloads and metrics, comparison paths, repetitions, uncertainty rules, and stopping conditions before candidate timing. It SHALL distinguish existing-test timing from added-test cost and profiling from uninstrumented acquisition. Changes to the plan SHALL retain the reason and earlier evidence.

#### Scenario: A favorable diagnostic suggests changing the target

- **WHEN** an isolated native operation improves but the registered public read does not
- **THEN** the diagnostic does not replace the registered acceptance metric after acquisition

### Requirement: Measurement compares equivalent complete work

Reference and experimental runs SHALL use matched release builds, dependencies, host conditions, data, options, budgets, residency, concurrency, warmup, and complete result consumption. Repeated counterbalanced runs SHALL verify expected results and cache outcomes. Invalid windows SHALL retain their rejection reasons and SHALL NOT support a gain claim.

#### Scenario: One core retains fewer entries

- **WHEN** eviction or bypass changes the resident catalogue between compared memory runs
- **THEN** the evaluation rejects an equal-residency saving claim

#### Scenario: Warm reads fall back to MongoDB

- **WHEN** a registered hit window performs unexpected origin reads or cache misses
- **THEN** that window is invalid for hit-performance acceptance

### Requirement: Evaluation measures complete runtime and process resources

The evaluation SHALL report public-operation P50/P95/P99 latency, throughput, CPU per completed read, incremental RSS/PSS, peak memory, and memory per resident entry. It SHALL separate interpreter/import cost, stored BSON, retained metadata, transient work, and allocator retention where measurable, state exclusions, and include Python and native allocations.

#### Scenario: Native allocations escape Python heap tracing

- **WHEN** the experimental core stores keys or values outside the Python allocator
- **THEN** process measurements include that memory and Python heap savings alone do not establish a total saving

### Requirement: Small results and long keys have runtime controls

The registered evaluation SHALL include complete public reads for the same small-entry and long-key shapes used for memory measurement, in both execution models. Warm and cold runs SHALL report latency, CPU, throughput, and cache outcomes under matched residency and eviction conditions. These controls SHALL be registered before candidate acquisition.

#### Scenario: Native metadata improves memory density

- **WHEN** the small-result or long-key memory workload qualifies
- **THEN** its corresponding runtime controls still gate retention and cannot be replaced by larger-document controls

### Requirement: Runtime controls match qualifying memory occupancy

Each small-entry or long-key memory checkpoint eligible to qualify native retention SHALL have registered public-read runtime controls at its observed resident-entry count, BSON budget, and occupancy. Both cores SHALL match the starting checkpoint and report entry count, resident BSON, budget occupancy, catalogue coverage, and subsequent eviction behavior. A smaller working set SHALL NOT qualify a higher-occupancy memory claim.

#### Scenario: Memory savings are measured after populating a large catalogue

- **WHEN** a checkpoint's memory reduction is used to qualify retention
- **THEN** its warm and cold runtime controls exercise that checkpoint's occupancy rather than the public harness's default key count

### Requirement: Performance controls exercise one contended core

The evaluation SHALL compare reference/native public-read performance with multiple synchronized reader threads sharing one synchronous manager while that manager processes real change-stream invalidations. It SHALL report throughput, latency, CPU/read, cache outcomes, and actual invalidation pressure under matched residency and offered load. Separate per-process managers or correctness-only tests SHALL NOT satisfy this control.

#### Scenario: Reader processes own separate managers

- **WHEN** the ordinary public harness runs concurrent independent workers
- **THEN** those results do not establish performance under contention within one core

#### Scenario: Writes occur without processed invalidations during reads

- **WHEN** a claimed contention window contains writes but no observed invalidation processing while readers are active
- **THEN** that window is invalid for the contention control

### Requirement: Final-wheel controls cover shared-cache regressions

The final ordinary wheel SHALL be compared against frozen main for representative shared-cache warm reads, fresh-process import/startup wall time and CPU, per-process RSS, and worker-plus-owner group PSS. Repeated matched controls SHALL verify equal residency and expected cache outcomes. Shared regressions SHALL follow the same approval rule even when owner/publication algorithms are unchanged.

#### Scenario: The combined native binary increases shared startup memory

- **WHEN** the native local core qualifies but the final wheel reproducibly increases shared-path startup cost or memory
- **THEN** the change remains unqualified for retention until the regression is corrected or explicitly approved

#### Scenario: A shared warm control fetches from the origin

- **WHEN** a registered warm shared-read window produces unexpected cache outcomes or origin reads
- **THEN** that window is rejected rather than used as regression evidence

### Requirement: Material gains use the agreed thresholds

Native retention SHALL require at least 10% lower complete public-operation latency or CPU per completed read, or at least 20% lower incremental equal-residency process memory, for a predeclared workload and metric. Repeated matched runs SHALL distinguish the gain from measurement noise. An isolated helper speedup SHALL NOT satisfy this gate.

#### Scenario: Only key preparation improves

- **WHEN** a native helper is faster but no registered complete-operation or memory metric meets its threshold
- **THEN** the candidate does not qualify for replacement

#### Scenario: Memory is the qualifying benefit

- **WHEN** the registered memory workload meets the threshold with equal retained entries and BSON
- **THEN** the report identifies memory as the benefit without claiming a read speedup

### Requirement: Regressions require explicit approval

Every reproducible runtime, resource, or existing-test slowdown SHALL be investigated and corrected or receive explicit user approval before native retention. A gain in another metric SHALL NOT waive this rule. Inconclusive control results SHALL remain visible and SHALL NOT be described as proof of no regression.

#### Scenario: Memory improves while small hot reads slow down

- **WHEN** a candidate meets the memory threshold but reproducibly increases small-read latency
- **THEN** it remains unqualified unless the user explicitly approves that measured trade-off

### Requirement: Measured source remains reproducible after cleanup

The report SHALL identify an immutable reachable commit containing each measured candidate's exact source, native build configuration, and harness integration. Rejected code SHALL be removed only after its commit is retained in the PR's published history or another durable published ref. Reproduction commands SHALL check out that commit; untracked raw outputs SHALL NOT substitute for source.

#### Scenario: A rejected candidate is removed

- **WHEN** the final tree removes unsuccessful native code or selection hooks
- **THEN** the report's candidate commit remains fetchable and its documented build and acquisition commands remain applicable to that revision

### Requirement: Reports retain decisions and limitations

The evaluation SHALL retain a concise report with workload scope, attribution, reproduction commands, limitations, rejected alternatives, and the final retention decision. Raw outputs SHALL remain untracked. Observed memory improvements SHALL NOT be presented as an RSS bound.

#### Scenario: A candidate has mixed measured effects

- **WHEN** the report records a qualifying result or a negative decision
- **THEN** it retains unfavorable and inconclusive observations alongside the decision's supporting evidence

### Requirement: Qualified native integration completes in the same change

The change SHALL deliver either a qualified native default or the reference implementation, with a reproducible report. A qualifying candidate SHALL be integrated, documented, and re-evaluated as the ordinary distribution build in the same branch and PR. A report, nondefault feature, or follow-up issue alone SHALL NOT complete a successful implementation.

#### Scenario: Neither candidate nor correction qualifies

- **WHEN** the registered investigation reaches its stopping condition without a qualifying result
- **THEN** it records a negative or inconclusive decision without extending the search indefinitely

#### Scenario: The candidate qualifies

- **WHEN** all applicable conformance and performance gates are satisfied
- **THEN** the same PR retains the native implementation in ordinary builds and qualifies that final integration against the registered baseline
