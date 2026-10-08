# Spec Delta

## ADDED Requirements

### Requirement: Multi-process comparisons match aggregate application work

Multi-process investigations SHALL compare independent managers with matched no-stream controls at multiple worker counts, covering idle and concurrent read/write traffic. Aggregate application work SHALL remain fixed across worker counts, and reports SHALL identify manager, database, and actual stream counts.

#### Scenario: Worker count increases

- **WHEN** an investigation compares one worker with several workers against the same databases
- **THEN** it replays the same aggregate read/write schedule and working set, reports the per-worker allocation, and verifies the resulting stream counts rather than attributing extra application traffic to stream duplication

#### Scenario: A manager fails to establish its stream

- **WHEN** any required manager fails startup or warmup
- **THEN** the run is recorded as failed and cannot count as a healthy multi-process sample

### Requirement: Multi-process stream costs are isolated in idle and active traffic

The investigation SHALL measure idle polling and active stream delivery with matched stream-only and no-stream controls. Those paths SHALL use identical application writes and connected-worker counts without cached application reads. Evidence of active duplication SHALL be eligible to justify a prototype even when idle duplication is below the registered threshold.

#### Scenario: Active streams have significant duplicated cost

- **WHEN** complete active stream-only evidence passes the registered opportunity rule while idle evidence does not
- **THEN** the investigation proceeds to the prototype and records the active workload and execution model that justified it

#### Scenario: Cached reads change MongoDB work

- **WHEN** native managers avoid application refetches in an active window
- **THEN** those measurements are reported as workload context and do not substitute for isolated stream-delivery cost

### Requirement: Multi-process reports separate resource owners

Reports SHALL separate MongoDB CPU, worker CPU, harness CPU, configured cache limits, resident cache bytes, and observed process memory. Wire-command counts SHALL come from command observation. Shared-delivery measurements SHALL additionally include coordinator and IPC costs; unavailable metrics SHALL be explicit and SHALL NOT support a saving claim.

#### Scenario: A cache budget is reported

- **WHEN** workers each have a configured cache budget
- **THEN** the report distinguishes the summed budget ceilings from populated cache bytes and measured private process memory, without claiming that sharing invalidations removes cached-value duplication

#### Scenario: Work runs in child processes

- **WHEN** the harness measures a multi-process window
- **THEN** it collects each child's CPU and memory independently and identifies observer overhead rather than treating parent process CPU as total worker CPU

### Requirement: Shared-invalidation prototype work follows a frozen triage rule

The investigation SHALL freeze workload schedules, repetitions, uncertainty treatment, and benefit thresholds before timed sampling. It SHALL build a shared-delivery prototype only when complete baseline evidence satisfies that rule. Negative, failed, and inconclusive results SHALL remain visible; an unmet rule SHALL support deferral for the tested workload rather than a universal rejection.

#### Scenario: Duplication cost is inconclusive

- **WHEN** required baseline evidence is missing or its uncertainty overlaps the registered benefit threshold
- **THEN** the investigation records an inconclusive outcome and skips the prototype without inventing a measured improvement

### Requirement: Shared-delivery statistical decisions match the recommendation scope

The investigation SHALL preregister each recommendation's resource benefit and required safety conjunction. Multiplicity adjustment SHALL cover alternative recommendations rather than every component of an all-must-pass recommendation. Repeated-block and lag-capture inference SHALL use exact empirical block enumeration, disclose its statistical assumptions, and preserve failing or missing components.

#### Scenario: One safety component fails

- **WHEN** a candidate has a resource saving but any required subscriber, paired-run, or execution-model safety component fails or is unresolved
- **THEN** that scoped recommendation cannot pass, and passing results elsewhere cannot override the component

#### Scenario: A recommendation passes

- **WHEN** all components of a preregistered scoped recommendation pass
- **THEN** the report applies the registered correction for selecting among alternative recommendations and does not claim simultaneous confidence coverage for every component interval

### Requirement: Shared-delivery lag evidence uses a complete registered capture plan

Each active comparison SHALL preregister lag capture-window count, equal event count, and event separation per subscriber and variant. Lag inference SHALL resample complete contiguous windows uniformly, include scheduled events delivered during bounded drain, and reject missing events or captures. A duration-bounded application window SHALL NOT be treated as an event-count capture window.

#### Scenario: The active application window ends before delivery completes

- **WHEN** scheduled invalidations arrive during bounded drain
- **THEN** their lag remains in the registered capture sequence rather than being omitted to improve the measured percentile

#### Scenario: A subscriber has an incomplete capture

- **WHEN** any required subscriber or variant lacks its registered event counts or separation
- **THEN** the comparison is recorded as incomplete and cannot support that group's recommendation

### Requirement: Shared-delivery feasibility accounts for continuity failures

The feasibility assessment SHALL explain detection, cache bypass, clearing, and safe recovery for coordinator loss, stalled delivery, sequence gaps, subscriber join/rejoin, coordinator restart, and stream history loss. Any prototype SHALL exercise these cases and demonstrate that reads spanning uncertainty cannot repopulate stale cache state.

#### Scenario: A subscriber falls behind

- **WHEN** a prototype subscriber exceeds its registered delivery limit or loses an event
- **THEN** it disables lookup and admission, clears affected state when continuity is lost, and cannot resume cache use solely because a heartbeat or connection is healthy

#### Scenario: A read spans recovery

- **WHEN** a read starts before delivery becomes unavailable and completes after recovery
- **THEN** its stale result cannot be admitted under the restored availability state

### Requirement: Shared-delivery research keeps reads local in both execution models

A shared-delivery prototype SHALL retain process-local cached values and perform no IPC or database round trip on a healthy local cache lookup. It SHALL evaluate synchronous, asyncio, and mixed subscribers against the same ordering and recovery model, and distinguish cache-core or transport measurements from supported-manager end-to-end measurements.

#### Scenario: An asyncio subscriber joins synchronous subscribers

- **WHEN** both execution models consume one prototype coordinator's invalidations
- **THEN** both apply the same continuity rules, local lookup uses locally maintained state, and blocking transport reception does not run on the asyncio event loop

#### Scenario: Only transport primitives were measured

- **WHEN** the prototype has not exercised the supported manager's complete read path
- **THEN** its report labels lookup and transport timings accordingly and makes no supported-manager latency claim

### Requirement: Shared-invalidation recommendations preserve evidence limits

The investigation SHALL retain a concise Markdown report with reproduction commands, all registered outcomes, coordination alternatives, and a defer-or-pursue recommendation linked to issue #87. Raw results SHALL remain untracked. A positive result SHALL justify only a separate implementation proposal, with topology, trust, and deployment limitations stated.

#### Scenario: Research supports further work

- **WHEN** a prototype demonstrates a benefit under the registered rule
- **THEN** the report explains remaining integration and operating costs, identifies the scope tested, and does not present shared invalidation as a supported public feature

#### Scenario: Research ends without a prototype

- **WHEN** baseline evidence does not justify prototype work
- **THEN** the report still answers the coordination and safety questions through an explicitly unvalidated design assessment and records why the prototype was skipped
