# real-server-benchmarking Specification

## Purpose

This capability measures the cache's real-world benefit and guards against regressions against a real, externally hosted MongoDB deployment, complementing the disposable local replica set used by every other test tier.

## Requirements

### Requirement: A benchmark exercises a real external MongoDB deployment

The repository SHALL provide a benchmark test that connects to a real, externally hosted MongoDB replica set using a connection string sourced from the contributor's local, gitignored configuration rather than from repository state or a disposable container.

#### Scenario: A contributor with a configured real deployment runs the local benchmark command

- **WHEN** a contributor with a configured real-deployment connection string runs the documented local benchmark command
- **THEN** the benchmark connects to that real deployment and executes its workload against it

### Requirement: The benchmark only runs in a runnable local environment

The benchmark SHALL skip, with a visible and explicit reason, whenever it runs in CI or whenever no real-deployment connection string is configured locally. It SHALL NOT fail the surrounding test command in either case, and it SHALL NOT attempt a network connection when skipping.

#### Scenario: CI runs the documented local benchmark command

- **WHEN** the documented local benchmark command runs in CI
- **THEN** the benchmark reports an explicit skip and the command's overall result is unaffected by the benchmark

#### Scenario: A contributor without a configured real deployment runs the documented local benchmark command

- **WHEN** a contributor without a configured real-deployment connection string runs the documented local benchmark command
- **THEN** the benchmark reports an explicit skip identifying the missing configuration, and every other test in the command continues to run

### Requirement: The benchmark workload models concurrent independent applications within a small shared deployment's limits

The benchmark's workload SHALL run a writing/updating workload and a reading workload as independent, concurrently running processes against the same real deployment, modeling two independent application components sharing one database. The workload's size and rate SHALL stay within the throughput and storage limits of a small, shared, free-tier deployment, and the benchmark SHALL complete in under 20 seconds.

#### Scenario: The benchmark runs against a configured real deployment

- **WHEN** the benchmark runs its workload against a configured real deployment
- **THEN** the writing/updating process and the reading process run concurrently as independent processes, the workload stays within the declared throughput and storage envelope, and the benchmark completes in under 20 seconds

### Requirement: The benchmark proves the cache's benefit over direct, uncached access

The benchmark SHALL measure the reading workload's performance once through the cache and once through direct, uncached access to the same real deployment, using the same operations and data shape for both, in the same run. It SHALL fail if the cached measurement is not at least twice as fast as the direct, uncached measurement.

#### Scenario: The cached and direct phases both complete

- **WHEN** the benchmark measures the cached reading workload and the direct, uncached reading workload against the same real deployment in the same run
- **THEN** the benchmark fails unless the cached measurement is at least twice as fast as the direct, uncached measurement

### Requirement: The benchmark guards against wall-clock regressions

The benchmark SHALL assert that its measured wall-clock time for each phase stays within a fixed ceiling recorded from an initial run against the real deployment. Each wall-clock ceiling SHALL carry enough margin above its initial measurement to tolerate ordinary shared-deployment variance without masking a material regression.

#### Scenario: A change makes either measured phase materially slower

- **WHEN** the benchmark's measured wall-clock time for either phase exceeds its recorded ceiling
- **THEN** the benchmark fails and identifies which phase exceeded its ceiling

### Requirement: The benchmark guards against uncached round-trip regressions

The benchmark SHALL assert that its measured count of server round trips for the direct, uncached phase stays within a fixed ceiling recorded from an initial run against the real deployment. The uncached phase's round-trip count is deterministic and independent of deployment variance, so its ceiling SHALL match the initial measurement exactly.

#### Scenario: A change makes the uncached phase send an unexpected number of round trips

- **WHEN** the uncached phase's measured round-trip count differs from its recorded ceiling
- **THEN** the benchmark fails

### Requirement: The benchmark guards against cached round-trip regressions

The cached phase's round-trip count SHALL also carry a fixed ceiling recorded from an initial run, with its own small margin, since a concurrently running writer can occasionally invalidate a document between reads and cause a small, non-deterministic number of cache-miss round trips even absent any regression.

#### Scenario: A change makes the cached phase materially chattier

- **WHEN** the cached phase's measured round-trip count exceeds its recorded, margin-carrying ceiling
- **THEN** the benchmark fails

### Requirement: The benchmark records non-gating network-bandwidth evidence from the real deployment

Around the existing cached and uncached read phases, the benchmark SHALL collect network-bandwidth measurements (bytes in, bytes out, request count, and query-operation count) for the real deployment's primary process via the Atlas Admin API, invoked through the contributor's already-authenticated `atlas` CLI session. These measurements SHALL be recorded alongside each phase's existing wall-clock and round-trip-count results as retained evidence, and SHALL NOT gate the benchmark's pass/fail result: at the deployment's supported measurement granularity, and given the shared deployment's background activity, a numeric bandwidth threshold from a single run is not reliable enough to certify a regression, so this measurement informs investigation rather than failing the benchmark. The benchmark SHALL NOT attempt to collect process-level CPU measurements from the real deployment, since the configured deployment's tier returns no data points for those measurement types.

#### Scenario: Bandwidth evidence accompanies both phases

- **WHEN** the benchmark completes its cached and uncached phases
- **THEN** the recorded output includes network-bandwidth evidence for each phase, and neither phase's pass/fail result depends on that evidence

#### Scenario: The deployment tier returns no CPU data

- **WHEN** the benchmark queries the real deployment's process measurements
- **THEN** it does not request or report process-level CPU values, and an empty CPU result from the API is not treated as a failure

#### Scenario: Atlas metrics are transiently unavailable

- **WHEN** the Atlas Admin API call for bandwidth measurements fails or times out
- **THEN** the benchmark still completes and reports the missing evidence rather than failing the benchmark on account of non-gating evidence

### Requirement: The real connection string is never exposed through default failure output

The fixture holding the real deployment's connection string SHALL NOT expose the plaintext connection string (credentials included) through its default string representation. Its `repr()` and `str()` output SHALL be redacted, distinct from the raw value actually used to open connections, so that a test failure's default traceback output does not leak the plaintext connection string to logs or a terminal, independent of any `-s`, `-v`, or `--showlocals` flag choice.

#### Scenario: A test using the real connection string fails

- **WHEN** a test that holds the real-deployment connection string fixture fails an assertion
- **THEN** pytest's default traceback output does not include the plaintext connection string

### Requirement: A pre-flight connectivity check runs before the timed benchmark window

Before starting the timed benchmark window, the benchmark SHALL perform a pre-flight connectivity check against the real deployment that is excluded from the measured wall-clock window, so a first connection's DNS resolution, TLS handshake, and deployment-side routing warm-up cost does not inflate the measured window.

#### Scenario: The session's first connection is cold

- **WHEN** the benchmark's first connection to the real deployment in a session incurs cold-start latency
- **THEN** the pre-flight check absorbs that warm-up cost outside the timed window

#### Scenario: The pre-flight check itself fails

- **WHEN** the pre-flight connectivity check cannot reach the real deployment
- **THEN** the benchmark reports that failure distinctly from a timing or cache-benefit assertion failure
