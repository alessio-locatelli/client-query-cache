## ADDED Requirements

### Requirement: Initial stream failures have a retry cooldown

Each database SHALL retain an initial-startup retry deadline after failure. Before that deadline, reads SHALL bypass caching without starting another stream, waiting for the deadline, or emitting another startup warning. A later read at or after the deadline SHALL permit one new attempt. These rules SHALL apply equally to unsupported servers, watch-permission failures, and transient startup failures.

#### Scenario: Reads arrive during cooldown

- **WHEN** multiple eligible reads target a database before its failed startup's retry deadline
- **THEN** they execute uncached with no additional version checks or stream-open attempts attributable to activation
- **AND** health remains `startup_failed` and ordinary bypasses retain the `stream_unavailable` reason

#### Scenario: A retry becomes eligible

- **WHEN** a read arrives at or after the deadline
- **THEN** one new startup attempt is permitted without a timer or background startup retry
- **AND** success restores normal caching eligibility while another failure sets a new deadline

#### Scenario: The failure is persistent

- **WHEN** startup repeatedly fails because the server lacks required features or watch permissions
- **THEN** the same cooldown policy limits repeated attempts and warnings without permanently disabling later recovery

### Requirement: Startup retry delays are bounded and increasing

Initial retry delays SHALL use exponential caps starting at 100 milliseconds, doubling to at most 30 seconds, with each delay sampled between half its cap and the cap. Deadline comparisons SHALL use a monotonic clock. Successful startup SHALL discard its startup retry history. Established-stream reconnect behavior SHALL retain its existing policy.

#### Scenario: Successive initial attempts fail

- **WHEN** successive initial startup attempts fail
- **THEN** their delay caps are 100, 200, 400 milliseconds and continue doubling to a maximum of 30 seconds
- **AND** each delay is positive and no greater than 30 seconds

### Requirement: Database startups do not serialize unrelated activation

Activation SHALL perform database I/O without holding a coordinator-wide lock. At most one startup attempt SHALL be in progress for each database. Reads encountering that database's pending activation SHALL bypass caching without waiting for the startup. Activation and use of another database SHALL be able to proceed independently.

#### Scenario: Two databases activate concurrently

- **WHEN** startup for database A is blocked in network I/O and a read activates database B
- **THEN** B can finish startup before A is released

#### Scenario: An established database is read during another startup

- **WHEN** database A is starting and database B already has a healthy stream
- **THEN** B's reads can use its cache without waiting for A

#### Scenario: Several reads activate one database

- **WHEN** several reads reach a database whose initial attempt is still pending
- **THEN** exactly one attempt runs and the other reads bypass caching while health reports `connecting`

### Requirement: Pending activation owns public health reporting

An unpublished initial activation SHALL report `connecting` through public health inspection even after native startup succeeds. Live supervisor health SHALL become observable only after successful publication. Closed management SHALL take precedence over pending activation.

#### Scenario: Native startup succeeds before publication

- **WHEN** startup has succeeded internally but its owner has not yet published the supervisor
- **THEN** concurrent health inspection reports `connecting`, and competing reads continue to bypass caching

#### Scenario: Publication completes

- **WHEN** the owner completes publication of the successfully started supervisor
- **THEN** subsequent health inspection reports its current supervision state

#### Scenario: Closure wins the publication race

- **WHEN** closure begins after native startup succeeds but before publication
- **THEN** health inspection reports `closed` and the late attempt cannot expose `healthy`

### Requirement: Closing owns pending stream activation

Closure SHALL reject new activation and make all tracked databases unavailable before waiting for cleanup. Async closure SHALL establish this state before its first suspension, independently of cleanup task scheduling. Pending startups SHALL remain owned until their native resources and workers are released. An attempt finishing after closure begins SHALL NOT publish a usable stream or restore cache availability. Closure SHALL release retained retry state.

#### Scenario: Close races a successful startup

- **WHEN** closure begins while a stream-open operation is pending and that operation subsequently succeeds
- **THEN** its stream is closed, no worker remains running after closure completes, and the database remains unavailable

#### Scenario: Cleanup for one database blocks

- **WHEN** shutdown waits for database A's worker while database B is tracked
- **THEN** B is already unavailable even if its cleanup has not yet completed

#### Scenario: Activation runs before the async cleanup task

- **WHEN** async closure reaches its first suspension and an already-ready activation runs before the retained cleanup task begins executing
- **THEN** activation raises the existing closed-coordinator lifecycle error without starting a supervisor or opening a stream
- **AND** public health reports `closed` and all tracked databases are already unavailable

### Requirement: Async shutdown cleanup survives caller cancellation

Async closure SHALL finish its owned resource cleanup before propagating caller cancellation. Concurrent and subsequent closure calls SHALL join the same cleanup without duplicating it. Manager-owned cache release SHALL also complete before cancellation propagates.

#### Scenario: The shutdown caller is cancelled during cleanup

- **WHEN** native stream cleanup is blocked and the caller executing async closure is cancelled
- **THEN** cleanup remains active and the caller does not finish before it
- **AND** after native cleanup is released, streams and workers are released before cancellation propagates

#### Scenario: Other callers close during or after cancelled shutdown

- **WHEN** another caller closes while cancellation-resistant cleanup is pending, or after it finishes
- **THEN** it joins or observes that same cleanup result without skipping unfinished cleanup or starting duplicate native close operations

#### Scenario: Cancellation is requested repeatedly

- **WHEN** the shutdown caller is cancelled again while waiting for cleanup
- **THEN** owned cleanup still finishes before that caller propagates cancellation

#### Scenario: A manager shutdown caller is cancelled

- **WHEN** manager closure is cancelled during coordinator cleanup
- **THEN** the manager's cache is released after coordinator cleanup and before cancellation propagates

### Requirement: Interrupted activation releases its reservation

Async cancellation and unexpected startup exceptions SHALL propagate after releasing activation ownership and cleaning any opened native resources. They SHALL NOT leave a database permanently connecting, publish a usable stream, or overwrite closed management. Cancellation SHALL NOT count as a failed startup retry attempt.

#### Scenario: Async activation is cancelled

- **WHEN** the startup-owning caller is cancelled before startup completes
- **THEN** its resources are cleaned and another read can initiate startup if the manager remains open
- **AND** health reports `startup_failed` until another attempt and no cooldown is imposed by cancellation

#### Scenario: An unexpected exception interrupts activation

- **WHEN** startup raises an exception outside the supported startup-failure boundary
- **THEN** the original exception propagates, the reservation is released, and a subsequent read can try again

### Requirement: Startup guidance distinguishes retries from freshness

Public operations guidance SHALL describe initial retry cooldown, read-driven recovery, startup and reconnection health observations, and uncached fallback. It SHALL distinguish these states from event catch-up and direct users to native reads when freshness is required.

#### Scenario: An operator diagnoses unavailable caching

- **WHEN** an operator follows startup-failure guidance
- **THEN** the guide explains the warning, `startup_failed`, `stream_unavailable`, subsequent `connecting` and `healthy`, and why reads continue uncached between attempts
