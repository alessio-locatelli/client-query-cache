# Spec Delta

## Purpose

This capability provides reproducible evidence of how direct MongoDB reads compare with independent per-worker cache managers when several application worker processes serve reads while writes run at the same time.

## ADDED Requirements

### Requirement: Concurrent worker workloads freeze their protocol

Before any comparison window runs, a concurrent worker benchmark SHALL preregister its data, hot-key cardinality, document size, read and write mix, offered load, window duration, worker counts, execution model and block count. Smoke and exploratory results SHALL be labelled and SHALL NOT be reported as registered evidence.

#### Scenario: A parameter changes after measurement starts

- **WHEN** a registered workload value changes after any comparison window has run
- **THEN** the change requires a new registration version and fresh comparisons, and the earlier outcome stays recorded

### Requirement: Offered load comes from baseline calibration

The offered read rate SHALL be selected by the registered calibration rule over both compared paths at every registered worker count. The rate SHALL be validated before it is frozen. The same aggregate rate and the same seeded read and write schedules SHALL apply to every path and worker count.

#### Scenario: One direct worker cannot sustain the proposed rate

- **WHEN** validation shows that a path completes too few offered reads at the proposed rate
- **THEN** the registered rule lowers the common rate and validates it again, or it reports an inconclusive setup

### Requirement: Compared paths perform equivalent application work

Direct reads and cached reads SHALL use the same host, topology, data, queries, read preference, read concern, decode work, per-worker concurrency and offered schedule. Writes SHALL be issued throughout each measurement window, at the same time as reads.

#### Scenario: A path cannot complete the offered schedule

- **WHEN** a window overflows its request bound or completes fewer reads than the registered completion floor
- **THEN** the window is reported as overloaded and is not treated as equivalent completed work

### Requirement: Every worker serves the whole hot set

Each worker's request sequence SHALL draw from the entire registered hot set. Hot keys SHALL NOT be partitioned among workers, so that each worker's cache faces the same key population that a load-balanced deployment would send it.

#### Scenario: Four workers serve the hot set

- **WHEN** a four-worker window completes
- **THEN** every worker has read keys from across the whole hot set, and writes have targeted keys that every worker reads

### Requirement: Reports retain throughput and request latency

For each path and worker count, reports SHALL retain completed throughput and the P50, P95 and P99 of request latency. Latency SHALL be measured from each request's scheduled issue time, so that queueing delay is included.

#### Scenario: Latency is compared across paths

- **WHEN** the report compares cached and direct reads at one worker count
- **THEN** it shows each percentile for both paths, from the same registered schedule

### Requirement: Reports account CPU and memory by owner

Reports SHALL separately measure MongoDB CPU, aggregate worker CPU, harness CPU and aggregate worker memory. Reports SHALL state each measure's scope. Memory shared between processes SHALL be counted once.

#### Scenario: MongoDB work falls while worker memory grows

- **WHEN** cached workers reduce MongoDB CPU but hold more resident memory than direct workers
- **THEN** the report shows both measures, without combining them into a single score

### Requirement: Cache outcome recordings stay separate from request outcomes

Reports SHALL show hit, miss and bypass recordings as counts per window, with bypass recordings broken down by reason. Reports SHALL NOT divide bypass recordings by completed requests or present them as mutually exclusive request outcomes.

#### Scenario: One request records several bypass reasons

- **WHEN** a window records more bypass reasons than it completed cached requests
- **THEN** the report shows the counts as recorded and makes no bypass-rate claim

### Requirement: Reports verify change-stream ownership

Reports SHALL count change-stream openings from observed commands. Each steady-state window SHALL have one stream per worker on the cached path and none on the direct path.

#### Scenario: A worker opens an unexpected stream

- **WHEN** a steady-state window's observed stream openings differ from the registered count
- **THEN** the window is reported as unhealthy and excluded from comparison

### Requirement: Invalidation lag is labelled with its clocks

Reports SHALL measure invalidation lag from each write's server commit time to its processing in a worker. Reports SHALL state the clock sources, the calibrated offset and the uncertainty. A lag percentile SHALL be claimed only when the registered event floor is met.

#### Scenario: Too few invalidations are captured

- **WHEN** a window captures fewer invalidation events than the registered floor
- **THEN** the report gives no lag percentile for that window and states why

### Requirement: Concurrent worker results are published with their limits

The research report SHALL give paired-block estimates with stated uncertainty, the measured host and topology, its limits and reproduction commands. Raw output SHALL remain untracked. Public guides SHALL cite only measured figures, stated with the workload and topology they apply to.

#### Scenario: A reader applies the result to another deployment

- **WHEN** a public guide cites a concurrent worker figure
- **THEN** it names the measured workload, worker counts and single-host topology, and does not present the figure as a guarantee
