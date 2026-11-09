# Spec Delta

## MODIFIED Requirements

### Requirement: Candidate selection is private and explicit

The evaluation SHALL select isolated installed production builds before manager creation, without adding a public backend option or bundling a reference engine. Ordinary process-local construction SHALL use the native core. Setup failure SHALL be visible rather than silently substituting another implementation.

#### Scenario: A normal application creates a manager

- **WHEN** an application uses the qualified default distribution build
- **THEN** it receives the native process-local implementation through the existing manager API without selecting a backend

#### Scenario: Experimental setup fails

- **WHEN** a native evaluation process cannot load its selected installed build
- **THEN** the evaluation reports failure and does not record execution from a different build as the selected build

### Requirement: Evaluated cores satisfy the existing read contract

The evaluation SHALL verify production native cores against the existing cache-core, cached-read-api, and change-stream-coherency requirements using specified expected results and invariants, without a reference engine. It SHALL exercise both execution models, all supported read methods, custom codecs, document classes, and bypass/error behavior. An unsupported or divergent case SHALL block acceptance of the candidate production build.

#### Scenario: A custom codec or session changes read behavior

- **WHEN** a conformance case uses application decoding or a session-bound operation
- **THEN** the production cores preserve the specified result, error, cache outcome, and caller-owned resource behavior

### Requirement: Key equivalence is preserved across native ownership

Production keys SHALL preserve the specified equality and distinctions, including identity numeric equivalence, discriminator numeric subtypes, field order, collation, namespace, and read shape. Hash collisions SHALL NOT establish equality. Python values without a native representation SHALL NOT silently become misses or additional bypasses.

#### Scenario: Similar keys have different meanings

- **WHEN** two supported discriminators differ only in a type or ordering that the specified contract distinguishes
- **THEN** neither reads the other's cached value

#### Scenario: A supported leaf requires Python equality

- **WHEN** a supported key contains a value without a compact native representation
- **THEN** production execution preserves the specified key behavior and accounts for its retained Python resources

### Requirement: Workloads and decision rules precede candidate measurements

The evaluation SHALL register immutable revision identities, hypotheses, target workloads and metrics, isolated installed-build comparisons, repetitions, uncertainty rules, and stopping conditions before timing a candidate production build. It SHALL distinguish existing-test timing from added-test cost and profiling from uninstrumented acquisition. Changes to the plan SHALL retain the reason and earlier evidence.

#### Scenario: A favorable diagnostic suggests changing the target

- **WHEN** an isolated native operation improves but the registered public read does not
- **THEN** the diagnostic does not replace the registered acceptance metric after acquisition

### Requirement: Measurement compares equivalent complete work

Independently installed baseline and candidate production builds SHALL use matched release settings, dependencies, host conditions, data, options, budgets, residency, concurrency, warmup, and complete result consumption. Repeated counterbalanced runs SHALL verify expected results and cache outcomes. Invalid windows SHALL retain their rejection reasons and SHALL NOT support a gain claim.

#### Scenario: One core retains fewer entries

- **WHEN** eviction or bypass changes the resident catalogue between compared memory runs
- **THEN** the evaluation rejects an equal-residency saving claim

#### Scenario: Warm reads fall back to MongoDB

- **WHEN** a registered hit window performs unexpected origin reads or cache misses
- **THEN** that window is invalid for hit-performance acceptance

### Requirement: Evaluation measures complete runtime and process resources

The evaluation SHALL report public-operation P50/P95/P99 latency, throughput, CPU per completed read, incremental RSS/PSS, peak memory, and memory per resident entry. It SHALL separate interpreter/import cost, stored BSON, retained metadata, transient work, and allocator retention where measurable, state exclusions, and include Python and native allocations.

#### Scenario: Native allocations escape Python heap tracing

- **WHEN** an evaluated production build stores keys or values outside the Python allocator
- **THEN** process measurements include that memory and Python heap savings alone do not establish a total saving

### Requirement: Small results and long keys have runtime controls

The registered evaluation SHALL include complete public reads for the same small-entry and long-key shapes used for memory measurement, in both execution models. Warm and cold runs SHALL report latency, CPU, throughput, and cache outcomes under matched residency and eviction conditions. These controls SHALL be registered before installed-build comparison.

#### Scenario: Native metadata improves memory density

- **WHEN** the small-result or long-key memory workload qualifies
- **THEN** its corresponding runtime controls still gate acceptance and cannot be replaced by larger-document controls

### Requirement: Runtime controls match qualifying memory occupancy

Each small-entry or long-key memory checkpoint used to substantiate a production memory improvement SHALL have registered public-read runtime controls at its observed resident-entry count, BSON budget, and occupancy. Both installed production builds SHALL match the starting checkpoint and report entry count, resident BSON, budget occupancy, catalogue coverage, and subsequent eviction behavior. A smaller working set SHALL NOT qualify a higher-occupancy memory claim.

#### Scenario: Memory savings are measured after populating a large catalogue

- **WHEN** a checkpoint's memory reduction supports a production memory claim
- **THEN** its warm and cold runtime controls exercise that checkpoint's occupancy rather than the public harness's default key count

### Requirement: Performance controls exercise one contended core

The evaluation SHALL compare public-read performance of independently installed baseline and candidate production builds with multiple synchronized reader threads sharing one synchronous manager while that manager processes real change-stream invalidations. It SHALL report throughput, latency, CPU/read, cache outcomes, and actual invalidation pressure under matched residency and offered load. Separate per-process managers or correctness-only tests SHALL NOT satisfy this control.

#### Scenario: Reader processes own separate managers

- **WHEN** the ordinary public harness runs concurrent independent workers
- **THEN** those results do not establish performance under contention within one core

#### Scenario: Writes occur without processed invalidations during reads

- **WHEN** a claimed contention window contains writes but no observed invalidation processing while readers are active
- **THEN** that window is invalid for the contention control

### Requirement: Final-wheel controls cover shared-cache regressions

For a candidate production build, the final ordinary wheel SHALL be compared against frozen main for representative shared-cache warm reads, fresh-process import/startup wall time and CPU, per-process RSS, and worker-plus-owner group PSS. Repeated matched controls SHALL verify equal residency and expected cache outcomes. Each wheel SHALL run in its own isolated installation. Shared regressions SHALL follow the same approval rule even when owner/publication algorithms are unchanged.

#### Scenario: The combined native binary increases shared startup memory

- **WHEN** a candidate production wheel reproducibly increases shared-path startup cost or memory
- **THEN** the change remains unqualified for acceptance until the regression is corrected or explicitly approved

#### Scenario: A shared warm control fetches from the origin

- **WHEN** a registered warm shared-read window produces unexpected cache outcomes or origin reads
- **THEN** that window is rejected rather than used as regression evidence

### Requirement: Proven gains qualify regardless of percentage

Production evaluation SHALL accept a stable improvement in a predeclared complete public-operation or equal-residency resource metric when repeated matched measurements distinguish it from noise. No minimum percentage SHALL apply. Correctness failures SHALL block acceptance; material adverse trade-offs SHALL require discussion and a documented decision. Isolated helper timings SHALL NOT establish a complete-operation benefit.

#### Scenario: A small improvement is established

- **WHEN** repeated matched measurements establish a 0.5% improvement beyond uncertainty and no material adverse trade-off remains unresolved
- **THEN** its size alone does not prevent acceptance of the production change

#### Scenario: Only key preparation improves

- **WHEN** a native helper is faster but no registered complete-operation or resource improvement is established beyond noise
- **THEN** the helper timing alone does not qualify the candidate

#### Scenario: Memory is the qualifying benefit

- **WHEN** a registered memory workload establishes a saving with equal retained entries and BSON
- **THEN** the report identifies memory as the benefit without claiming a read speedup

### Requirement: Regressions require explicit approval

Every reproducible runtime, resource, or existing-test slowdown SHALL be investigated. Unavoidable nonmaterial costs SHALL be documented; material adverse costs SHALL be corrected or discussed and explicitly approved before accepting a production change. A gain in another metric SHALL NOT waive this rule. Inconclusive control results SHALL remain visible and SHALL NOT be described as proof of no regression.

#### Scenario: Memory improves while small hot reads slow down

- **WHEN** a candidate establishes a memory improvement but materially increases small-read latency
- **THEN** it remains unqualified unless the user explicitly approves that measured trade-off

### Requirement: Measured source remains reproducible after cleanup

The report SHALL identify an immutable reachable commit containing each compared production build's exact source, native build configuration, and harness integration. Historical reproduction SHALL use that commit rather than preserving removed implementations in the current tree. Reproduction commands SHALL check out that commit; untracked raw outputs SHALL NOT substitute for source.

#### Scenario: A rejected candidate is removed

- **WHEN** the final tree removes unsuccessful native code or selection hooks
- **THEN** the report's measured-build commit remains fetchable and its documented build and acquisition commands remain applicable to that revision

### Requirement: Reports retain decisions and limitations

The evaluation SHALL retain a concise report with workload scope, attribution, reproduction commands, limitations, rejected alternatives, and the production-change decision. Raw outputs SHALL remain untracked. Observed memory improvements SHALL NOT be presented as an RSS bound.

#### Scenario: A candidate has mixed measured effects

- **WHEN** the report records a qualifying result or a negative decision
- **THEN** it retains unfavorable and inconclusive observations alongside the decision's supporting evidence

### Requirement: Internal migrations have independently attributable decisions

Optional replacements of production hot-path components SHALL each have a registered target and disposition. It SHALL compare each retained stage with its predecessor and the final ordinary build with frozen current main. One component's gain SHALL NOT qualify another component lacking a demonstrated benefit. Negative or inconclusive alternatives SHALL preserve the preceding production behavior and their evidence. This rule SHALL NOT justify retaining development-only runtime code.

#### Scenario: Capture improves while query preparation does not

- **WHEN** only capture has a confirmed registered benefit
- **THEN** capture is retained, query preparation remains unchanged, and both outcomes appear in the report

#### Scenario: Earlier optimizations change the next bottleneck

- **WHEN** the preceding retained stage already eliminates the cost targeted by another replacement
- **THEN** the later disposition uses that stage as its control rather than claiming the earlier gain again

### Requirement: Staged acquisition avoids repeated full campaigns

Each focused production-build comparison SHALL use one matched benchmark lasting less than thirty minutes, including repetitions and teardown. Broader campaigns SHALL require a registered validation need for the affected production behavior. Routine per-component full campaigns and automatic uncertainty campaigns SHALL NOT be required. Further acquisition SHALL identify a concrete failure, invalid result, correction, or unresolved adverse signal.

#### Scenario: Three candidates pass their short comparisons

- **WHEN** the combined ordinary build is ready for broad performance validation
- **THEN** a broader campaign runs only when the registered validation need calls for it, comparing isolated production builds rather than automatically repeating historical migration campaigns

#### Scenario: A comparison remains noisy

- **WHEN** the short benchmark reaches its declared budget without a clear result
- **THEN** its uncertainty is retained and does not automatically start another acquisition cohort

## REMOVED Requirements

### Requirement: Qualified native integration completes in the same change

**Reason**: This requirement governed the completed migration from the Python engine to the native default. Keeping that historical selection gate would permit retaining or restoring a reference implementation after the production-only policy takes effect.

**Migration**: Ordinary construction, conformance, installed-build measurements, regression approval, and reproducible reports remain governed by their current requirements. Future optional production changes use those requirements; cleanup of development-only implementations does not reopen the completed backend-selection decision.
