## ADDED Requirements

### Requirement: README presents illustrative latency evidence

The README SHALL reuse the public benchmark guide's illustrative read-latency chart after the value proposition and before the quick start. Its title and accessible description SHALL identify the comparison as illustrative. A short caption SHALL name the measured deployments, state that results vary, and link to the benchmark guide for methodology and limitations.

#### Scenario: A reader evaluates cached-read latency

- **WHEN** a reader scans the README's performance illustration
- **THEN** they see the local MongoDB and Atlas M0 measurements as illustrative results and can reach their methodology without a full benchmark explanation in the README
