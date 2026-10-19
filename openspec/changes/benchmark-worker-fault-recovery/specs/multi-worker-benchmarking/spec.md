# Spec Delta

## ADDED Requirements

### Requirement: Fault trials preregister their settings

Before any timed trial runs, its registration SHALL specify the fault cases, topology for each case, injection time, observation intervals, recovery criterion, repetition count, and offered workload.

#### Scenario: A trial is planned from its registration

- **WHEN** the runner plans a timed fault trial
- **THEN** the case's topology, injection time, observation intervals, recovery criterion, repetition count, and offered workload come from its registration

### Requirement: Registration changes preserve earlier outcomes

Changing any registered setting after timed trials start SHALL require a new registration version. Earlier outcomes SHALL remain recorded under the version that produced them.

#### Scenario: The recovery criterion is tightened after a trial

- **WHEN** the recovery criterion changes after any timed trial has run
- **THEN** a new registration version repeats every affected trial, and the earlier results remain in the report

### Requirement: Recovery criteria bound unresolved requests

The registration SHALL specify the recovery bucket duration, minimum completion fraction, request P99 multiplier, and backlog grace multiplier. Recovery analysis SHALL mark a bucket's backlog clear only when every request scheduled before that bucket ends is resolved by the bucket end plus the registered backlog grace multiplied by the before-interval P99.

#### Scenario: An overdue request keeps a recovery bucket uncleared

- **WHEN** a request scheduled before a bucket ends remains unresolved past the registered backlog grace
- **THEN** that bucket's backlog is not clear and the bucket cannot satisfy the recovery criterion

### Requirement: Fault trials use separate workers and a disposable replica set

Each trial SHALL run a group of separate worker processes against a disposable replica set.

#### Scenario: A fault trial starts separate workers

- **WHEN** a registered timed trial starts
- **THEN** it runs its worker group as separate processes against the disposable replica set

### Requirement: Fault trials inject real transport and server events

Trials SHALL inject connection loss by severing TCP connections, primary failover by stepping down the primary and allowing an election, and worker restart by killing and replacing a process. Unavailable resume history SHALL be injected when a stream reopens, so the manager runs its real recovery path.

#### Scenario: A connection-loss fault severs worker TCP connections

- **WHEN** a trial reaches its registered connection-loss injection time
- **THEN** the harness severs the worker's TCP connections through its faultable proxy

#### Scenario: A history-loss fault reaches the manager on stream reopening

- **WHEN** an independent worker reopens its change stream after history-loss injection
- **THEN** the worker's real manager handles the unavailable resume history

#### Scenario: A restart fault replaces the killed process

- **WHEN** a worker is killed at the registered restart injection time
- **THEN** the harness starts a replacement worker with the remaining scheduled requests

### Requirement: Fault trials timestamp the first injection action

The actual injection offset SHALL use the first worker-side action timestamp for a multi-worker control fault, or the timestamp immediately before the replica-set stepdown command is issued.

#### Scenario: Worker control dispatch is delayed

- **WHEN** dispatch to a worker is delayed before its proxy or stream-history action
- **THEN** the trial records the action's monotonic timestamp as the actual injection offset and checks it against the registered schedule tolerance

### Requirement: Fault trials declare path applicability

Each fault case SHALL run only on paths to which its mechanism applies. Reports SHALL mark excluded paths as not applicable and SHALL NOT report a measurement for them.

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

#### Scenario: A request crosses a bucket boundary within the registered grace

- **WHEN** a request scheduled before a recovery bucket ends completes within the registered grace after that boundary
- **THEN** the boundary crossing alone does not prevent the bucket from meeting the recovery criterion

#### Scenario: A stalled request exceeds the registered grace

- **WHEN** a request scheduled before a recovery bucket ends remains unresolved beyond the registered grace
- **THEN** the bucket does not meet the recovery criterion even if its P99 and completion fraction pass

#### Scenario: Cached workers bypass during failover

- **WHEN** cached workers record stream-unavailable bypasses after a stepdown
- **THEN** the report shows those counts by reason and the time until hits resume, without dividing them by requests

#### Scenario: A killed worker never returns

- **WHEN** a worker-restart trial's replacement never becomes ready while the surviving workers serve their own requests normally
- **THEN** the trial is reported as not recovered, because each bucket completes too few of its scheduled requests

#### Scenario: Recovery comes after the registered deadline

- **WHEN** a trial meets the recovery criterion only after the registered deadline, or never meets it
- **THEN** the trial is reported as not recovered, and its after-fault interval is reported as unavailable rather than truncated

#### Scenario: A later bucket has a latency spike

- **WHEN** a bucket meets the registered recovery criterion before the deadline and a later bucket fails that criterion
- **THEN** recovery remains recorded at the first passing bucket, and the later bucket failure remains visible in the timeline

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

### Requirement: Fault trials separate induced failures from setup failures

A trial SHALL be a failed setup when, before injection, it observes a failed command, an election, clock drift or a host clock step. It SHALL also be a failed setup when, after injection, it observes clock drift, a host clock step, an election outside the stepdown case, or a command error outside the case's registered error classes. Induced command errors and the stepdown election SHALL be recorded as fault evidence.

#### Scenario: Reads fail with network errors after a connection loss

- **WHEN** reads fail with network errors after a `connection-loss` injection
- **THEN** the trial records the failures by command and error class as evidence, instead of rejecting the window

#### Scenario: An election occurs during a connection-loss trial

- **WHEN** a primary election is observed in a case other than stepdown
- **THEN** the trial is recorded as a failed setup

#### Scenario: A stepdown trial elects no new primary

- **WHEN** the replica set reports no new writable primary within the registered deadline after a stepdown
- **THEN** the trial is recorded as a failed setup and is not used as recovery evidence

#### Scenario: A stepdown leaves no writable primary during calibration

- **WHEN** a periodic clock sample during the planned stepdown election reports no writable primary
- **THEN** the sampler skips that sample and resumes on its next cadence, while other sampling errors still fail setup

### Requirement: Fault trials record harness write outcomes

Each harness write in a fault trial SHALL be recorded as acknowledged, failed with its error class, or of unknown outcome when it fails after it may have reached the server.

#### Scenario: A write may have reached the server before failing

- **WHEN** a harness write fails after it may have reached the server and its outcome cannot be determined
- **THEN** the trial records its outcome as unknown rather than assuming the write was not applied

### Requirement: Fault trials bound invalidations by stream lifetime

A cached worker's expected invalidations SHALL be bounded below by the acknowledged writes committed after its current stream lifetime began. They SHALL be bounded above by adding acknowledged writes whose commit time can't be ordered against the opening, and every unknown-outcome write in the window.

#### Scenario: A replacement worker starts after earlier writes

- **WHEN** a replacement worker's stream opens after acknowledged writes were committed
- **THEN** those earlier writes are excluded from its expected invalidations, and only writes committed after its stream opened are required

#### Scenario: A write cannot be ordered against the stream opening

- **WHEN** an acknowledged write's commit time cannot be ordered against the current stream's opening
- **THEN** it counts toward the worker's upper bound on expected invalidations but not its lower bound

#### Scenario: A write's outcome remains unknown

- **WHEN** a harness write in the fault window has an unknown outcome
- **THEN** it counts toward the upper bound on expected invalidations, regardless of when its failure was observed, but not toward the lower bound

### Requirement: Harness write failures do not alone invalidate fault trials

A failed harness write SHALL NOT, by itself, make a fault trial a failed setup.

#### Scenario: A write fails during failover

- **WHEN** a harness write fails with an election error during a stepdown trial
- **THEN** the trial records the write's outcome and excludes it from the lower bound on expected invalidations
- **AND** that write failure alone does not make the trial a failed setup

### Requirement: Fault windows verify initial stream ownership

Before injection, every fault window SHALL observe exactly one stream opening for each cached worker and none for direct workers. After injection, the report SHALL show stream reopenings as recovery evidence and SHALL NOT reject a trial for them.

#### Scenario: Streams reopen after history loss

- **WHEN** cached workers reopen their streams after a `history-loss` injection
- **THEN** the trial keeps the reopenings as evidence, having verified one initial opening per cached worker

### Requirement: Multi-member topology is declared and observed

Failover trials SHALL use a replica set with at least three members, each with declared CPU and memory limits. Each trial SHALL record the primary's identity before and after the fault.

#### Scenario: The same member is primary after a stepdown

- **WHEN** the recorded primary after a stepdown trial is the member that stepped down, with no intervening election observed
- **THEN** the trial is recorded as a failed setup
