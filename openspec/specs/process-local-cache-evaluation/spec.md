# process-local-cache-evaluation Specification

## Purpose

Evaluate and integrate native process-local cache storage through representative application reads, retaining qualifying implementations in the same change on comparable correctness, runtime, and memory evidence.

## Requirements

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

The evaluation SHALL register immutable revision identities, hypotheses, target workloads and metrics, isolated installed-build comparisons, repetitions, uncertainty rules, and stopping conditions before timing a candidate production build. It SHALL distinguish existing-test timing from added-test cost and profiling from uninstrumented acquisition. Changes to the plan SHALL retain the reason and earlier evidence.

#### Scenario: A favorable diagnostic suggests changing the target

- **WHEN** an isolated native operation improves but the registered public read does not
- **THEN** the diagnostic does not replace the registered acceptance metric after acquisition

### Requirement: Measurement compares equivalent complete work

Comparisons SHALL match release settings, unrelated dependencies, host, data, options, residency, concurrency and warmup; counterbalanced repetitions SHALL consume results and verify outcomes. Cache-core evaluations SHALL use independently installed production builds. Focused substitutions SHALL permit equivalent private-operation snippets, with bounded installed-build controls for affected paths. Invalid windows SHALL retain reasons and SHALL NOT support gain claims.

#### Scenario: One core retains fewer entries

- **WHEN** eviction or bypass changes the resident catalogue between compared memory runs
- **THEN** the evaluation rejects an equal-residency saving claim

#### Scenario: Warm reads fall back to MongoDB

- **WHEN** a registered hit window performs unexpected origin reads or cache misses
- **THEN** that window is invalid for hit-performance acceptance

#### Scenario: A private utility has no production binding

- **WHEN** a focused dependency substitution is measured through a compile-time-only snippet
- **THEN** both variants perform equivalent complete target operations under matched conditions
- **AND** installed-build controls separately verify the affected production path without adding a runtime testing interface

### Requirement: Evaluation measures complete runtime and process resources

Cache-core evaluations SHALL report public-operation P50/P95/P99 latency, throughput, CPU per completed read, incremental RSS/PSS, peak memory, and memory per resident entry. They SHALL separate interpreter/import cost, stored BSON, retained metadata, transient work, and allocator retention where measurable, state exclusions, and include Python and native allocations. Focused dependency substitutions SHALL instead measure their affected costs and representative integrated regression controls.

#### Scenario: Native allocations escape Python heap tracing

- **WHEN** an evaluated production build stores keys or values outside the Python allocator
- **THEN** process measurements include that memory and Python heap savings alone do not establish a total saving

#### Scenario: A dependency replaces a bounded utility

- **WHEN** a focused dependency substitution affects formatting, hashing, storage bookkeeping, or synchronization without replacing the cache core
- **THEN** its evaluation measures the affected operation and relevant allocation, retention, or contention costs
- **AND** integrated controls exercise the affected cache paths without requiring every cache-core evaluation metric

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

Cache-core evaluations SHALL compare synchronized public reads on one manager during real invalidations, reporting throughput, latency, CPU/read, outcomes and invalidation pressure under matched residency/load. Focused substitutions SHALL use representative contention controls when lock behavior or changed protected work can materially affect contention. Separate managers or correctness-only tests SHALL NOT satisfy contention controls.

#### Scenario: Reader processes own separate managers

- **WHEN** the ordinary public harness runs concurrent independent workers
- **THEN** those results do not establish performance under contention within one core

#### Scenario: Writes occur without processed invalidations during reads

- **WHEN** a claimed contention window contains writes but no observed invalidation processing while readers are active
- **THEN** that window is invalid for the contention control

#### Scenario: A focused substitution does not affect locking

- **WHEN** a focused dependency substitution preserves lock behavior and has no material effect on protected work
- **THEN** it uses representative affected-operation controls without a mandatory contended-core benchmark

#### Scenario: Protected work changes without changing lock boundaries

- **WHEN** a substitution changes computation, allocation or data-structure operations inside a potentially contended critical section
- **THEN** the evaluation assesses its effect on protected work and uses focused concurrent operations on the same manager when that effect can be material
- **AND** unchanged locking boundaries alone do not exempt it from contention measurement

### Requirement: Final-wheel controls cover shared-cache regressions

Cache-core evaluations SHALL compare final ordinary wheels against frozen main for shared warm reads, fresh-process startup wall time/CPU, per-process RSS and worker-plus-owner PSS. Focused dependency substitutions SHALL instead use bounded final-wheel controls for affected paths and plausible binary/startup resource effects. Both SHALL use isolated installations, matched residency and verified cache outcomes; regressions SHALL follow the approval rule.

#### Scenario: The combined native binary increases shared startup memory

- **WHEN** a candidate production wheel reproducibly increases shared-path startup cost or memory
- **THEN** the change remains unqualified for acceptance until the regression is corrected or explicitly approved

#### Scenario: A shared warm control fetches from the origin

- **WHEN** a registered warm shared-read window produces unexpected cache outcomes or origin reads
- **THEN** that window is rejected rather than used as regression evidence

#### Scenario: A focused substitution reaches the final build

- **WHEN** accepted dependency substitutions are combined into an ordinary wheel
- **THEN** its affected-path and resource controls use the duration-selection and stopping rules for staged acquisition
- **AND** unmeasured resource metrics remain explicit limitations rather than triggering a full cache-core campaign

### Requirement: Proven gains qualify regardless of percentage

Cache-core evaluations SHALL qualify gains in complete public-operation or equal-residency resource metrics. Focused dependency substitutions SHALL also qualify on a reproducible affected-operation gain or demonstrated removal of custom machinery with lower net maintenance complexity. No minimum percentage SHALL apply. Correctness failures SHALL block acceptance; material adverse trade-offs SHALL require approval. Helper timings SHALL NOT establish complete-operation gains.

#### Scenario: A small improvement is established

- **WHEN** repeated matched measurements establish a 0.5% improvement beyond uncertainty and no material adverse trade-off remains unresolved
- **THEN** its size alone does not prevent acceptance of the production change

#### Scenario: Only key preparation improves

- **WHEN** a native helper is faster but no registered complete-operation or resource improvement is established beyond noise
- **THEN** its timing alone does not qualify a cache-core migration
- **AND** a focused dependency substitution can qualify at the measured helper scope without claiming a complete-read speedup

#### Scenario: Memory is the qualifying benefit

- **WHEN** a registered memory workload establishes a saving with equal retained entries and BSON
- **THEN** the report identifies memory as the benefit without claiming a read speedup

#### Scenario: A crate removes custom bookkeeping

- **WHEN** a focused substitution removes custom machinery and its adaptation code leaves lower net maintenance complexity
- **THEN** it can qualify on maintenance value with matched regression measurements and preserved behavioral contracts
- **AND** uncertain performance results remain explicitly uncertain and cannot be described as proof of no regression

### Requirement: Regressions require explicit approval

Every reproducible runtime, resource, or existing-test slowdown SHALL be investigated. Unavoidable nonmaterial costs SHALL be documented; material adverse costs SHALL be corrected or discussed and explicitly approved before accepting a production change. A gain in another metric SHALL NOT waive this rule. Inconclusive control results SHALL remain visible and SHALL NOT be described as proof of no regression.

#### Scenario: Memory improves while small hot reads slow down

- **WHEN** a candidate establishes a memory improvement but materially increases small-read latency
- **THEN** it remains unqualified unless the user explicitly approves that measured trade-off

### Requirement: Measured source remains reproducible after cleanup

Retained reproduction instructions SHALL use stable integrated source and sufficient build, workload and variant-reconstruction details, not assumed survival of PR branches or pre-merge SHAs. Material SHALL be retained according to its maintenance or review value. Discarded experiments without either value SHALL NOT require permanent refs or copies. Raw outputs SHALL NOT substitute for reproducible source.

#### Scenario: A rejected candidate is removed

- **WHEN** the final tree removes unsuccessful native code or selection hooks
- **THEN** retained reproduction instructions reconstruct useful experiments from stable source without requiring an abandoned commit
- **AND** experiments discarded under the artifact-retention policy carry no promise of future reproducibility

### Requirement: Reports retain decisions and limitations

Evaluation evidence SHALL retain workload scope, attribution, decisions, adverse results and limitations where useful for maintenance or review. Lasting maintenance evidence SHALL use tracked documentation; review-only evidence SHALL use the PR description. Material with neither value SHALL remain disposable. Retained reproduction instructions SHALL follow the source-reproducibility requirement. Raw outputs SHALL remain untracked; observed savings SHALL NOT imply an RSS bound.

#### Scenario: A candidate has mixed measured effects

- **WHEN** retained evidence records a qualifying result or a negative decision
- **THEN** unfavorable and inconclusive observations accompany the supporting evidence

### Requirement: Integrated development checks precede long acquisitions

Native internal replacements SHALL pass focused correctness cases and a simplified end-to-end acquisition through ordinary library construction before any multi-hour benchmark campaign. The simplified acquisition SHALL be bounded to five minutes, exercise affected execution models, verify values and cache outcomes, and expose setup or cleanup failures. Its timings SHALL NOT qualify retention.

#### Scenario: A capture replacement passes only its isolated accumulator tests

- **WHEN** a long confirmation campaign is about to start
- **THEN** it waits for a bounded real-database cold read, completed admission, and subsequent hit through the installed library

#### Scenario: Development acquisition exceeds its deadline

- **WHEN** setup, execution, or teardown exceeds the five-minute bound
- **THEN** the run fails visibly and the cause is resolved before expensive acquisition begins

### Requirement: Internal migrations have independently attributable decisions

Optional replacements of production hot-path components SHALL each have a registered target and disposition. It SHALL compare each retained stage with its predecessor and the final ordinary build with frozen current main. One component's gain SHALL NOT qualify another component lacking a demonstrated benefit. Negative or inconclusive alternatives SHALL preserve the preceding production behavior and their evidence. This rule SHALL NOT justify retaining development-only runtime code.

#### Scenario: Capture improves while query preparation does not

- **WHEN** only capture has a confirmed registered benefit
- **THEN** capture is retained, query preparation remains unchanged, and both outcomes appear in the report

#### Scenario: Earlier optimizations change the next bottleneck

- **WHEN** the preceding retained stage already eliminates the cost targeted by another replacement
- **THEN** the later disposition uses that stage as its control rather than claiming the earlier gain again

### Requirement: Staged acquisition avoids repeated full campaigns

Before each benchmark, the evaluation SHALL justify the smallest duration needed to distinguish noise from the net effect relevant to its decision. It SHALL select duration and stopping criteria from available variance/effect evidence or a minimal pilot, accounting for repetitions and controls. Longer runs or extensions SHALL require expected decision value; redundant precision SHALL NOT justify more acquisition. There SHALL be no universal duration cap.

#### Scenario: Three candidates pass their short comparisons

- **WHEN** the combined ordinary build is ready for performance validation
- **THEN** isolated production builds are compared using representative controls
- **AND** each control or broader campaign has a duration justification tied to an unresolved decision

#### Scenario: A comparison remains noisy

- **WHEN** a benchmark reaches its planned stopping point without a clear result
- **THEN** its uncertainty is retained and further acquisition requires evidence that it is likely to resolve a decision rather than merely narrow an interval

#### Scenario: A longer run can resolve a decision

- **WHEN** variance and effect estimates indicate that a longer acquisition can distinguish noise from the candidate's net effect
- **THEN** the evaluation can select or extend to that justified duration without a fixed per-candidate time limit

#### Scenario: Further precision would not affect adoption

- **WHEN** the existing evidence resolves the adoption decision and additional repetitions would only improve numerical precision
- **THEN** acquisition stops instead of repeating a benchmark campaign

#### Scenario: Compilation takes longer than acquisition

- **WHEN** a dependency experiment needs compilation before timing
- **THEN** build time is reported separately from acquisition
- **AND** rebuilding does not itself justify repeating completed measurements

### Requirement: Performance qualification accounts for selection and build variation

Performance-based qualification SHALL use prespecified error control across compared alternatives and metrics, with confirmation independent of selection data. Build-sensitive claims SHALL include independent compilation and, where applicable, profile training on both sides; identical-binary controls alone SHALL NOT establish build stability. Unresolved variation SHALL remain inconclusive. Maintenance qualification SHALL NOT imply a performance gain.

#### Scenario: A small apparent gain depends on one release build

- **WHEN** an apparent improvement is comparable to rebuild or profile-training variation
- **THEN** independent builds of both revisions and fresh measurements are required before qualifying the performance claim
- **AND** the claim remains inconclusive unless its uncertainty accounts for that variation

#### Scenario: Several candidates or metrics are screened

- **WHEN** the evaluation selects apparent winners from multiple comparisons
- **THEN** fresh confirmation uses the prespecified error control for the comparison family
- **AND** unadjusted screening intervals alone cannot qualify those winners
