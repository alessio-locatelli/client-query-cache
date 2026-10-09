# Spec Delta

## Purpose

This capability provides reproducible evidence for the resource savings, access costs, operating limits, and recovery safety of shared cached values across application processes on one host.

## ADDED Requirements

### Requirement: Shared-value comparisons freeze their decision protocol

Shared-value experiments SHALL preregister workload schedules, data, candidate selection, measurement ownership, uncertainty rules and promotion thresholds before candidate timing. Exploratory or smoke results SHALL be labelled and SHALL NOT support production promotion.

#### Scenario: A threshold changes after sampling

- **WHEN** an experiment changes its workload or acceptance criterion after seeing a result
- **THEN** it retains the original outcome and uses a new registration and fresh affected comparisons

#### Scenario: Prior invalidation evidence is available

- **WHEN** an existing study measures independent streams without a shared-value prototype
- **THEN** the shared-value report cites its limits without treating that evidence as proof of shared storage viability

### Requirement: Offered workloads follow baseline capacity calibration

Fixed-work offered rates SHALL be selected by preregistered baseline-only calibration on the test host and validated for both baseline paths at every required worker count and execution model. Rates and sample-preserving durations SHALL be frozen before candidate timing and applied equally across compared paths. Calibration SHALL NOT replace maximum-throughput experiments.

#### Scenario: Direct reads cannot sustain the proposed rate

- **WHEN** baseline validation overloads at the provisional offered rate
- **THEN** the registered selection rule lowers the common rate and revalidates baselines before freezing candidate workloads, or reports an inconclusive setup at its cap

#### Scenario: Candidate results suggest a more favorable rate

- **WHEN** candidate measurement has started
- **THEN** its results cannot select a replacement load; any recalibration uses baselines only, a new registration and fresh comparisons for all affected paths

#### Scenario: A lower rate extends an active window

- **WHEN** calibration extends the duration to preserve each path/run's percentile sample floor
- **THEN** baseline validation and candidate runs replay the same frozen read and write schedules, and samples from different runs cannot be pooled to satisfy that floor

### Requirement: Shared-value comparisons execute equivalent application work

The benchmark SHALL compare direct MongoDB reads, independent managers and shared storage with equivalent data, queries, decode work, concerns, concurrency and offered schedules. Fixed-work resource comparisons SHALL keep aggregate demand constant across worker counts. Hot-cache comparisons SHALL verify complete working-set residency; explicitly cold-miss comparisons SHALL begin without resident results.

#### Scenario: Workers cache the same catalogue

- **WHEN** multiple workers enter a hot-cache measurement
- **THEN** every independent worker has primed the same catalogue and the shared group has admitted it once under its group budget

#### Scenario: A path cannot sustain the offered schedule

- **WHEN** a path overflows its bounded request queue or misses required completions
- **THEN** its result exposes the overload and cannot qualify as equivalent completed work

#### Scenario: Cold-miss overhead is sampled

- **WHEN** the registered cold-miss phase begins
- **THEN** clients and metadata are warm but query results are absent, and its measurements are excluded from hot-hit and primed-memory gates

### Requirement: Shared-value memory accounting includes shared pages once

Reports SHALL distinguish configured budgets, resident encoded entries, private memory and observed group physical memory. Group accounting SHALL include coordinator, helper, mapped, pinned, buffered and transient allocations without double-counting shared pages. MongoDB and harness memory SHALL be measured separately with their metric scope stated.

#### Scenario: A mapped payload is visible in eight workers

- **WHEN** multiple processes map the same resident cache pages
- **THEN** the report counts their physical contribution once using proportional or equivalent accounting rather than summing RSS or omitting them from summed private memory

#### Scenario: Required memory accounting is unavailable

- **WHEN** the collector cannot account for shared-page or server-resident memory
- **THEN** it identifies the missing measure and makes no unsupported total-memory saving claim

### Requirement: Shared-value CPU and traffic accounting includes all owners

Reports SHALL measure aggregate worker, coordinator, helper, harness and MongoDB CPU, identifying observer overhead once. Reports SHALL separately measure MongoDB wire bytes, IPC bytes and applicable mapped-payload copy costs. Command observation SHALL establish stream openings and wire getMore counts.

#### Scenario: Coordination saves database work but consumes worker CPU

- **WHEN** a shared path reduces MongoDB CPU and adds IPC processing
- **THEN** the decision uses the registered total-cost measure and exposes both contributions

### Requirement: Shared-value scaling evidence retains latency and contention

Reports SHALL retain P50, P95 and P99 with counts for hits, misses, bypasses and application requests in both execution models at multiple worker counts. Reports SHALL distinguish fixed-demand comparisons from capacity experiments and identify queueing, saturation and the supported measured envelope.

#### Scenario: Coordinator throughput stops increasing

- **WHEN** additional concurrency increases queue delay without the registered throughput improvement
- **THEN** the capacity experiment follows its stopping rule and reports the limiting measured point without extrapolating unlimited worker scaling

#### Scenario: Async and synchronous workers share a group

- **WHEN** the mixed-worker validation runs
- **THEN** each model's latency and completion evidence remains available rather than only a pooled distribution

### Requirement: Shared-value recovery evidence exercises real process failures

A shared-value prototype SHALL exercise coordinator loss and stalls, worker recycling, stream interruption, history loss, backpressure and shutdown races. The report SHALL separate detection, safe readiness and rewarming durations and verify that obsolete captures and invalidated selections cannot serve later executions.

#### Scenario: A worker finishes a read across coordinator restart

- **WHEN** a native read starts under one coordinator incarnation and finishes after replacement
- **THEN** its result cannot populate the replacement cache using the old admission handle

#### Scenario: The watch stalls while cache RPC responds

- **WHEN** upstream progress exceeds its registered expiry despite a responsive transport
- **THEN** new selection and admission are disabled within the registered limit and recovery needs upstream progress

### Requirement: Shared-value decisions retain negative and uncertain evidence

Production promotion SHALL require every registered correctness and performance condition, with complete paired samples and declared uncertainty. The report SHALL retain failed, inconclusive and rejected candidate outcomes, measured limitations and reproduction commands. Raw benchmark output SHALL remain untracked.

#### Scenario: Memory improves while cache access is too slow

- **WHEN** a candidate saves memory but fails the registered latency condition
- **THEN** the report rejects production promotion for that candidate rather than treating the memory saving as sufficient

#### Scenario: No candidate qualifies

- **WHEN** all bounded candidate investigations fail or remain inconclusive
- **THEN** the delivered outcome is an evidence-backed recommendation without a supported shared-cache mode or unimplemented runtime promises in the main specifications

### Requirement: Negative outcomes preserve executable research evidence

A report SHALL identify executable measured source, configuration and dependency versions after unsupported production functionality is removed. The research implementation and required seams SHALL remain in the delivered tree or at a permanent published source revision linked by the report. The documented smoke invocation SHALL be verified from a clean checkout of that source before dependent code is removed.

#### Scenario: A rejected prototype depends on an internal core refactor

- **WHEN** cleanup would remove a seam required by the research runner
- **THEN** that seam remains with the research implementation or the report points to permanently published complete source and checkout-specific reproduction commands that still execute

### Requirement: Shared-value promotion uses independent confirmation blocks

Promotion inference SHALL use the registered independent confirmation blocks, excluding exploratory screening samples. Nested requests and capture windows SHALL NOT substitute for independent runs. Unstable bounds or uncertainty remaining at the registered sampling cap SHALL produce deferral rather than adaptive sampling for a passing result.

#### Scenario: A large request population spans only screening runs

- **WHEN** a candidate has many request samples but lacks the required independent confirmation blocks
- **THEN** its evidence remains descriptive and cannot pass promotion

#### Scenario: The sampling cap leaves an uncertain result

- **WHEN** a confidence bound straddles its criterion or registered sensitivity changes the verdict at the cap
- **THEN** the recommendation is inconclusive and production integration is deferred
