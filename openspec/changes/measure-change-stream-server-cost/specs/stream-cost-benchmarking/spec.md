# Spec Delta

## ADDED Requirements

### Requirement: Reports surface an explicit change-stream resource-cost comparison

For the `BALANCED` workload (concurrent insert and read traffic) at each configured data size, a controlled report SHALL present its raw-variant and cache-variant `container_cpu_seconds` values side by side as an explicit change-stream CPU-cost comparison, since the cache variant watches a change stream and the raw variant does not, and both already record this measurement per `stream-cost-benchmarking`'s existing controlled-measurement requirement. When the report was produced with `--direct-path-proxy` enabled, it SHALL likewise present the raw-variant and cache-variant `direct_path_bytes_sent`/`direct_path_bytes_received` values side by side as an explicit change-stream network-cost comparison. Absent `--direct-path-proxy`, the report SHALL note the network-cost comparison as unavailable for that run rather than omitting it silently. This comparison is retained evidence, not a pass/fail gate, consistent with this capability's existing treatment of CPU and timing measurements.

#### Scenario: A controlled report includes the BALANCED workload

- **WHEN** a controlled report includes the `BALANCED` workload's raw and cache variants
- **THEN** the report presents their `container_cpu_seconds` values side by side as the change-stream CPU-cost comparison

#### Scenario: The report was generated with byte-proxy mode enabled

- **WHEN** the report was generated with `--direct-path-proxy`
- **THEN** it also presents the raw-variant and cache-variant `direct_path_bytes` values side by side as the change-stream network-cost comparison

#### Scenario: The report was generated without byte-proxy mode

- **WHEN** the report was generated without `--direct-path-proxy`
- **THEN** the network-cost comparison is explicitly marked unavailable for that run, not silently omitted
