# shared-cache-benchmarking Specification

## Purpose

This capability provides reproducible evidence for the resource savings, access costs, operating limits, and recovery safety of shared cached values across application processes on one host.

## Requirements

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

Reports SHALL retain P50, P95 and P99 of the application-request population with counts of hits, misses and bypasses in both execution models at multiple worker counts. Reports SHALL label fixed-demand comparisons and closed-loop capacity windows separately, retaining every capacity window rather than only a maximum.

#### Scenario: Coordinator work bounds the shared path

- **WHEN** owner utilization is estimated from fixed-demand windows
- **THEN** the report labels any capacity extrapolation as unmeasured and does not present it as a measured operating envelope

#### Scenario: Async and synchronous workers share a group

- **WHEN** the mixed-worker validation runs
- **THEN** each model's latency and completion evidence remains available rather than only a pooled distribution

### Requirement: Shared-value recovery evidence exercises real process failures

A shared-value prototype SHALL exercise coordinator loss and stalls, worker recycling, stream interruption, history loss, backpressure and shutdown races against real processes, and SHALL verify that obsolete captures and invalidated selections cannot serve later executions. A report SHALL claim recovery durations only from timed fault trials.

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

### Requirement: Candidate prototypes follow measured cost floors

A shared-value study SHALL preregister its candidate selection rule and measure each candidate family's minimum added CPU per hit before building a full candidate. It SHALL NOT build a family whose floor exceeds the registered margin under the CPU criterion. Floor measurements SHALL be labelled exploratory, and the report SHALL retain every floor and the resulting choice.

#### Scenario: A round-trip floor exceeds the margin

- **WHEN** the minimal round trip of a family costs more CPU per hit than the registered margin allows
- **THEN** no full candidate of that family is built and the report records the floor and the exclusion

#### Scenario: Floor results favour one family

- **WHEN** floor diagnostics have ranked the eligible families
- **THEN** the ranking selects which candidates to build but cannot support production promotion

### Requirement: Locally served hits respect processed invalidations

When workers serve hits from owner-published shared state, a worker SHALL NOT serve an entry if the owner processed its invalidation, eviction or namespace reset, or its database's unavailability, before that read began. An event that the owner processes while a read is in progress SHALL NOT retract a value that the read has already validated.

#### Scenario: A write is processed before the read

- **WHEN** the owner has processed the invalidation of a cached document and a worker then reads that document
- **THEN** the worker does not serve the invalidated entry from shared state

#### Scenario: The database becomes unavailable

- **WHEN** the owner has marked a database unavailable
- **THEN** no worker serves a local hit for that database until the owner publishes its recovery

#### Scenario: A write races an admission

- **WHEN** the owner processes a document's invalidation after an admission for that document validated its capture but before the admission committed
- **THEN** the admission is not published and no worker serves that value locally

### Requirement: Locally served hits never return torn or reclaimed data

A locally served hit SHALL return either bytes that the owner published for the requested key or no value. A read that overlaps publication, removal or reuse of the same space SHALL be detected and its bytes SHALL NOT be decoded. An inconsistent location read SHALL NOT access memory outside the shared mapping.

#### Scenario: Space is reused during a copy

- **WHEN** the owner removes an entry and reuses its space while a worker is copying it
- **THEN** the worker discards the copy and does not serve it

#### Scenario: A location is read mid-update

- **WHEN** a worker reads an entry location that the owner is rewriting
- **THEN** the read stays inside the mapping and is treated as absent

### Requirement: Owner-served hits use stable payload snapshots

When the owner keeps payloads in reusable shared storage, every hit it serves over RPC SHALL encode a snapshot taken while the payload was still valid. A concurrent removal or space reuse SHALL turn that read into a miss, never into a reply containing other data.

#### Scenario: An entry is evicted while an RPC hit is in flight

- **WHEN** the owner selects an entry for an RPC hit and another thread evicts it and reuses its space before the reply is encoded
- **THEN** the reply is a miss or carries the entry's original bytes

### Requirement: Local validation fences owner loss

Without contacting the owner, a worker SHALL stop serving local hits from an owner incarnation within the registered detection bound after that owner process exits, and once the incarnation's published upstream progress is older than the registered expiry. After attaching to a replacement owner, a worker SHALL NOT read the shared state published by an earlier incarnation.

#### Scenario: The owner is killed

- **WHEN** the owner process exits while workers serve local hits
- **THEN** every worker stops serving local hits within the registered detection bound and executes reads natively

#### Scenario: The watch stalls while the owner stays alive

- **WHEN** the owner is paused, or its change stream stops completing upstream polls
- **THEN** workers stop serving local hits once the published progress exceeds the registered expiry

#### Scenario: A replacement owner starts

- **WHEN** a worker attaches to a new owner incarnation
- **THEN** it serves local hits only from that incarnation's published state

### Requirement: Shared-state reclamation is bounded

Published shared state SHALL have registered size bounds. A paused, slow or crashed worker SHALL NOT delay the reclamation of removed entries or cause shared memory to grow.

#### Scenario: A worker dies during a read

- **WHEN** a worker is killed while it copies a published entry
- **THEN** the owner reclaims and reuses that entry's space without waiting for the worker

#### Scenario: Publication capacity is exhausted

- **WHEN** the resident entries exceed the registered publication capacity
- **THEN** shared memory stays within its bounds and unpublished entries are served only through owner selection

### Requirement: Workers cannot modify published state

The owner SHALL give workers no descriptor or mapping through which the published index or entries can be written, including descriptors reopened from ones the worker received. Writable per-worker state SHALL use separate shared objects that grant no access to the published index.

#### Scenario: A worker tries to write the index

- **WHEN** a worker writes through its index descriptor, maps it writable, makes its mapping writable, or reopens the descriptor read-write and writes
- **THEN** every attempt fails and the published state is unchanged

### Requirement: Owner-liveness detection does not compete for RPC replies

A worker SHALL detect owner exit only through a connection's sole reader. A liveness watcher SHALL NOT read from a connection that another reader uses for RPC replies.

#### Scenario: A synchronous worker watches the owner

- **WHEN** a synchronous worker issues RPC selections while its liveness watcher waits for owner exit
- **THEN** every RPC reply reaches its requester intact, and owner exit still sets the worker's detached state

### Requirement: Published state agrees with the authoritative cache

A candidate whose workers validate entries locally SHALL pass a differential check against the authoritative cache. The check covers generated sequences of admissions, writes, namespace resets, evictions and availability changes, and every locally served value SHALL equal the value the authoritative cache serves at the same point.

#### Scenario: A generated sequence invalidates a cached key

- **WHEN** a generated operation sequence leaves the authoritative cache unable to serve a key
- **THEN** the published state also serves no value for that key

### Requirement: Native research components are reproducible

Reports SHALL record the compiler toolchain version, locked native dependency versions and build configuration of every native component they measure. The documented reproduction commands SHALL build those components from repository sources.

#### Scenario: A native candidate is reproduced

- **WHEN** a contributor follows the report's reproduction commands from a clean checkout of the measured revision
- **THEN** the native components build from the committed sources and lockfile and the documented smoke run completes

### Requirement: Shared fault registrations declare timing applicability

Shared fault registrations SHALL declare, for each case, whether detection, first safe readiness, first post-recovery hit and full rewarming apply. Missing declarations SHALL be configuration errors. Frozen earlier registrations SHALL remain unchanged.

#### Scenario: An older registration has only case names

- **WHEN** a fault phase is requested without timing applicability
- **THEN** planning fails before starting processes

### Requirement: Shared fault trials retain event-relative timings

Every registered case and repetition SHALL run against disposable MongoDB with the registered worker group. Detection SHALL start at injection; recovery timings SHALL start at the recovery action. All events SHALL use one monotonic clock. Inapplicable intervals SHALL be explicitly unavailable, never zero.

#### Scenario: A case has no recovery action

- **WHEN** malformed input or publication stress completes
- **THEN** the report retains its safety evidence and marks recovery intervals inapplicable

### Requirement: Shared fault outcomes require safety and readiness

Each trial SHALL check its scenario's safety and recovery invariants. Readiness SHALL require owner database availability, fresh upstream progress and worker eligibility. Rewarming SHALL require the hot set resident and, for a local-index path, published. Analysis SHALL report every duration per repetition and fail any safety violation, missing applicable timing or readiness above the registered bound.

#### Scenario: Recovery is fast but a stale capture is admitted

- **WHEN** a trial violates a safety invariant
- **THEN** its repetition and case fail regardless of measured durations

#### Scenario: A worker is eligible before the owner has fresh progress

- **WHEN** upstream progress is not fresh
- **THEN** the trial does not record safe readiness

### Requirement: Locally captured misses preserve admission fencing

A research worker MAY capture a miss without an owner round trip. Admission SHALL reject captures spanning a processed write, namespace reset, owner replacement, database availability transition or expired upstream progress. The authoritative cache SHALL validate admission races after capture validation. Capture lifetime and transport buffers SHALL remain bounded; cancellation SHALL retain no owner capture.

#### Scenario: A previously uncached identity is written during a read

- **WHEN** the owner processes its write after local capture and before admission
- **THEN** admission rejects the captured value even if the core tracked no identity when the write arrived

#### Scenario: Progress expires and resumes during a read

- **WHEN** upstream progress expires between local capture and admission and subsequently resumes
- **THEN** the old capture remains inadmissible

#### Scenario: Validation races another write

- **WHEN** a write arrives after the owner's local-token validation
- **THEN** the core's identity capture prevents stale publication

#### Scenario: Reusable core guard sections

- **WHEN** concurrent admissions reuse the core's lock-order guard objects
- **THEN** namespace/LRU exclusion remains thread-local and lasts through the outermost section
- **AND** an exception releases the section without weakening later checks

#### Scenario: Namespace acquisition is interrupted

- **WHEN** acquiring a reused namespace lock raises before the primitive lock is held
- **THEN** its lock-order guard unwinds and later LRU/namespace exclusion remains correct

#### Scenario: Integer identities reuse a BSON envelope

- **WHEN** a signed 64-bit plain integer key uses the optimized wire path
- **THEN** its bytes and decoded type match the existing tagged BSON representation exactly
- **AND** damaged lengths, field names or terminators remain protocol errors

#### Scenario: A local capture is unavailable

- **WHEN** metadata, publication slots or attachment validity cannot authorize capture
- **THEN** the worker retains the owner selection or native bypass path

#### Scenario: A worker queues an admission

- **WHEN** a worker posts an encoded admission to its native session queue
- **THEN** the owner consumes only complete records, copies them before reuse and applies the same admission fencing
- **AND** a full queue uses bounded socket fallback when a data channel is available, otherwise skips admission while preserving the MongoDB result

#### Scenario: A native queue is available without a data socket

- **WHEN** a valid authenticated control mapping provides a native admission queue and an executor thread has no data socket or loses its data socket
- **THEN** the worker captures and queues eligible misses without an owner selection RPC or data-socket setup
- **AND** a full queue reuses the same encoded frame for socket fallback when that transport is available
- **AND** socket-only attachments retain data-channel reconnection and owner selection

#### Scenario: An endpoint closes while its control mapping still exists

- **WHEN** the closed endpoint receives an admission with a queue-capable reader
- **THEN** it drops the admission without publishing through that queue
- **AND** detached readers remain unable to capture or enqueue

#### Scenario: Sustained admissions use short queue drains

- **WHEN** an owner consumes queued admissions
- **THEN** it polls admission queues every millisecond until fifty milliseconds after the latest nonempty drain
- **AND** capture cleanup and recency sweeps retain their fifty-millisecond cadence
- **AND** quiet owners return to fifty-millisecond polling

#### Scenario: A queue peer sends a damaged record

- **WHEN** queue positions, frame boundaries or admission fields are malformed
- **THEN** the owner detaches that peer without processing an unbounded record or disrupting other sessions

### Requirement: Default identity classification retains request policy

An optimized default identity read SHALL retain per-request session and read-profile inspection, metadata eligibility, owner reattachment, codec normalization and the existing capture/admission authorities. Requests outside the optimized shape SHALL retain general classification.

#### Scenario: A session is bound after warming an integer identity

- **WHEN** the same default identity request executes inside a bound session
- **THEN** it bypasses the shared hit and executes through the driver's session policy

#### Scenario: Metadata discovers a default collation

- **WHEN** a default integer identity request first probes a collection with non-simple default collation
- **THEN** both that read and subsequent reads bypass the shared cache

#### Scenario: Identity-key eviction leaves the default shape unchanged

- **WHEN** a collection view repeats its portable default read shape after unrelated identity keys leave the bounded key cache
- **THEN** it reuses its previously encoded default shape
- **AND** other shapes retain existing key preparation

#### Scenario: Codec metadata cannot form a canonical key

- **WHEN** a valid codec contains unhashable metadata
- **THEN** constructing the view succeeds and reads preserve the existing native bypass

### Requirement: Miss optimization evidence repeats the complete protocol

A follow-up miss study SHALL preregister fresh baseline calibration and all version 5 phases, plus the version 6 timed fault protocol. Its miss P95 and P99 upper confidence bounds SHALL satisfy the registered direct-read delta at four and eight workers in both models. Missing phases, failed capacity windows or regressed hot and active criteria SHALL prevent promotion.

#### Scenario: Cold misses pass but capacity fails

- **WHEN** fresh cold comparisons meet their limit but any required capacity window fails
- **THEN** the report retains that failure and withholds promotion

### Requirement: Bounded research cursor hits use shared publication

Research adapters SHALL serve exact positive-limit find hits from shared publication after complete consumption and authoritative admission. They SHALL retain owner selection on local absence and existing cursor behavior, bounds and failure fences. Public cursor caching remains outside this research contract.

#### Scenario: Another worker reads a sorted result

- **WHEN** one worker fully consumes and admits a bounded sorted find and another executes the same shape
- **THEN** the second worker serves a local shared hit without selecting through the owner

#### Scenario: A result is not completely consumed

- **WHEN** a cursor is closed before complete consumption
- **THEN** it publishes no partial result

### Requirement: Research result publication respects all writes

Every processed collection write SHALL invalidate its published find results, including writes with identities that cannot be canonicalized. Unrelated identity publications SHALL remain usable. Eviction, namespace reset, database availability and owner loss SHALL retain their existing safety behavior.

#### Scenario: A write changes sorted membership

- **WHEN** a processed write changes membership or ordering after a bounded result was published
- **THEN** the next local lookup cannot serve that publication

#### Scenario: A write crosses capture

- **WHEN** a write occurs after miss capture and before admission
- **THEN** the result is not published
