# Spec Delta

## ADDED Requirements

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
