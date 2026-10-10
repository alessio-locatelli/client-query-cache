# Spec Delta

## ADDED Requirements

### Requirement: Fault trials freeze their protocol

Before any timed trial runs, fault trials SHALL preregister:

- the fault cases;
- the topology for each case;
- the injection time and observation intervals;
- the recovery criterion;
- the number of repetitions;
- the offered workload.

A change after trials start SHALL require a new registration version, and earlier outcomes SHALL stay recorded.

#### Scenario: The recovery criterion is tightened after a trial

- **WHEN** the recovery criterion changes after any timed trial has run
- **THEN** a new registration version repeats every affected trial, and the earlier results remain in the report

### Requirement: Fault trials inject real failures into real worker processes

Each trial SHALL run a group of separate worker processes against a disposable replica set. Trials SHALL use real transport and server events for:

- connection loss (severed TCP connections);
- primary failover (stepdown of the primary, followed by an election);
- worker restart (a killed process replaced by a new one).

Unavailable resume history SHALL be injected at the stream's reopening, so that the manager runs its real recovery path.

#### Scenario: A stepdown trial elects no new primary

- **WHEN** the replica set reports no new writable primary within the registered deadline after a stepdown
- **THEN** the trial is recorded as a failed setup and is not used as recovery evidence

#### Scenario: A fault does not apply to direct reads

- **WHEN** a case affects only change streams, such as unavailable resume history
- **THEN** the report marks the direct path as not applicable for that case and does not report a measurement for it

### Requirement: Fault reports describe recovery for each case

For each case and path, the report SHALL include:

- failed reads;
- the time from injection to meeting the registered recovery criterion;
- request latency percentiles in the registered intervals before, during and after the fault;
- bypass recordings by reason during the fault interval.

For cached workers, the report SHALL also include the time until stream health and cache hits resume. For worker restart, it SHALL include the replacement's time to readiness and its repriming misses.

#### Scenario: Cached workers bypass during failover

- **WHEN** cached workers record stream-unavailable bypasses after a stepdown
- **THEN** the report shows those counts by reason and the time until hits resume, without dividing them by requests

#### Scenario: Recovery comes after the registered deadline

- **WHEN** a trial meets the recovery criterion only after the registered deadline, or never meets it
- **THEN** the trial is reported as not recovered, and its after-fault interval is reported as unavailable rather than truncated

### Requirement: Fault trials account for every scheduled request

Each trial SHALL classify every scheduled request as completed, failed, interrupted with an unknown outcome, or undelivered. A trial SHALL be valid only when these counts add up to the offered schedule, and the report SHALL show all four counts for each trial. Measurements that a killed worker delivered before its termination SHALL be retained.

#### Scenario: A worker is killed mid-window

- **WHEN** a worker is killed while requests it owns are in flight or have not yet been reported
- **THEN** its delivered measurements stay in the trial, its unreported requests are counted as interrupted rather than completed or failed, and the four counts still add up to the offered schedule

### Requirement: Fault results stay separate from steady-state estimands

Fault trial measurements SHALL be compared only between paths within the same case and topology. They SHALL NOT be pooled into steady-state throughput, latency or resource estimands, or reported in place of them.

#### Scenario: A failover window has low throughput

- **WHEN** a stepdown trial completes fewer reads than a steady-state window at the same rate
- **THEN** the steady-state results are unchanged, and the fault report attributes the shortfall to that case

### Requirement: Invalidation resumes after recovery

After each recovered trial, every cached worker SHALL process the invalidation for a write committed after recovery, and SHALL return the written revision when it next reads that key. A trial that fails this check SHALL be reported as a correctness failure, not as a slow recovery.

#### Scenario: A worker keeps serving a pre-fault revision

- **WHEN** a cached worker returns an older revision of a probe key after it has processed that key's post-recovery invalidation
- **THEN** the trial fails as incorrect, and the report retains the failure

### Requirement: Multi-member topology is declared and observed

Failover trials SHALL use a replica set with at least three members, each with declared CPU and memory limits. Each trial SHALL record the primary's identity before and after the fault.

#### Scenario: The same member is primary after a stepdown

- **WHEN** the recorded primary after a stepdown trial is the member that stepped down, with no intervening election observed
- **THEN** the trial is recorded as a failed setup
