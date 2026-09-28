# Spec Delta

## MODIFIED Requirements

### Requirement: Controlled measurements are not generalized

The suite SHALL report monotonic wall time, benchmark-process CPU, and controlled MongoDB-container CPU for every controlled run. For every operation-bearing variant in a controlled run, it SHALL report the required per-variant latency distribution; an idle variant SHALL report the explicit zero-operation and no-latency-samples marker. If MongoDB-container CPU cannot be collected from the configured cgroup or runtime, setup SHALL fail and the run SHALL not produce a controlled report. Optional byte-proxy mode SHALL count only its direct benchmark path. It SHALL permit compressed or uncompressed traffic on that path and SHALL refuse unsupported TLS, discovery, or shared-connection configurations. The report SHALL identify the requested and verified negotiated compressor, or explicitly identify an uncompressed connection; a compressed run whose negotiated mode cannot be verified SHALL fail setup. CI SHALL retain these reports as workload and architectural cost evidence without using their absolute or cross-host timings as a pass/fail gate. This does not prohibit `performance-regression-guard` from gating a pull request on matched, same-run relative measurements of base and proposed implementations under its separate coverage and noise policy.

#### Scenario: Proxy mode is requested with compression

- **WHEN** a controlled benchmark requests byte-proxy mode with a supported wire compressor on an isolated direct connection
- **THEN** the benchmark counts the bytes crossing that path and identifies the verified negotiated compressor, without presenting those bytes as deployment-wide traffic

#### Scenario: A compressed connection is not established

- **WHEN** a compression comparison requests a compressor that is unavailable or is not negotiated with the server
- **THEN** setup fails rather than recording an uncompressed run under the requested compressor's label

#### Scenario: A workload variant is not primed

- **WHEN** a cache workload variant other than the oversized-result workload completes warmup without positive counter deltas for at least one cache admission and one cache hit for that variant
- **THEN** setup or report validation fails before sampled results are accepted

#### Scenario: Controlled container CPU is unavailable

- **WHEN** a controlled benchmark cannot collect MongoDB-container CPU from its cgroup or runtime
- **THEN** setup fails and the benchmark does not emit a controlled report with an incomplete CPU measurement

#### Scenario: A controlled report is slower than a historical report

- **WHEN** a controlled stream-cost report has a larger absolute timing value than a report from another run or host
- **THEN** CI retains the report without failing on that timing difference alone

## ADDED Requirements

### Requirement: Wire compression is compared on matched stream workloads

The benchmark SHALL compare no compression, Snappy, zlib, and Zstandard against the same isolated MongoDB server version, resource limits, document data, operation schedule, and direct client topology. Each mode SHALL have a no-stream control and a cache path with the library's normal database change stream. The matrix SHALL include an idle polling window and active read/write windows with small and large documents, so both the stream's steady cost and its cost during change delivery are visible. Runs SHALL reset application data, cache state, and stream cursor before each sample, warm up before measurement, repeat and counterbalance mode and path order, and record the actual operation and event counts. A failed or unmatched run SHALL invalidate the affected comparison.

#### Scenario: A four-mode report is produced

- **WHEN** the benchmark completes its comparison
- **THEN** every mode has matched no-stream and stream-watching measurements for the registered workloads, sizes, and repetitions, with counts and order recorded

#### Scenario: A mode silently executes fewer writes

- **WHEN** a run executes or observes fewer operations or change events than its matched schedule requires
- **THEN** report validation rejects that run as incomparable

### Requirement: Compression reports expose server, latency, and wire trade-offs

For every matched window, the report SHALL record MongoDB-container CPU time, monotonic elapsed time, and direct-path bytes sent and received, with the proxy's path scope stated. Active windows SHALL report sample count and at least p50, p95, and p99 for applicable read, write, and write-to-invalidation latency; idle windows SHALL explicitly report no operation latency samples. The report SHALL show each mode's stream-minus-control CPU and byte deltas alongside the absolute path values. It SHALL retain the individual repetitions and environment, compressor, workload, and sample metadata needed to reproduce the comparison, and SHALL identify any inconclusive or noisy result rather than converting it into a performance claim.

#### Scenario: A report attributes the stream's cost

- **WHEN** a reader compares one compressor's stream-watching path with its no-stream control
- **THEN** the report shows both paths' CPU and direct-path bytes and their difference, while labeling that difference an approximation of the stream's added cost

#### Scenario: An idle window is reported

- **WHEN** a window contains no sampled reads or writes
- **THEN** its CPU and byte measurements remain available and its operation latency is marked unavailable with zero samples

### Requirement: Compression guidance follows retained measurements

Public performance guidance SHALL link a retained, versioned four-mode report and name one recommended PyMongo client compressor setting for the measured workload, including no compression when warranted. The recommendation SHALL prioritize server CPU cost and write-to-invalidation latency associated with watching the change stream, then consider direct-path byte savings, and SHALL disclose material workload and environment limits. If the measurements do not distinguish the modes reliably, guidance SHALL retain the current no-compression PyMongo default and state that the comparison is inconclusive; it SHALL NOT claim that mode is universally fastest or cheapest. The benchmark SHALL NOT change the public cache API or silently override the caller's client configuration.

#### Scenario: One mode offers a clear trade-off

- **WHEN** repeated measurements support a recommendation under the registered decision rule
- **THEN** the guidance names that mode, links the report, and explains its CPU, latency, and network trade-offs for the library's change-stream workload

#### Scenario: Differences are within measurement noise

- **WHEN** the registered rule cannot distinguish a mode from no compression
- **THEN** guidance keeps no compression as the documented default and labels the result inconclusive rather than claiming a measured win
