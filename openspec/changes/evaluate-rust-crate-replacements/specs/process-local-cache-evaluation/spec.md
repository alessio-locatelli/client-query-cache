## MODIFIED Requirements

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

## ADDED Requirements

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
