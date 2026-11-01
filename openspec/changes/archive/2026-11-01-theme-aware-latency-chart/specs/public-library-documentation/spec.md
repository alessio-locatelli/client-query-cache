## ADDED Requirements

### Requirement: Latency chart follows the reader's appearance

The illustrative read-latency chart SHALL have light and dark variants. The README and the benchmark guide SHALL show the variant matching the reader's appearance.

#### Scenario: A reader uses a dark appearance

- **WHEN** a reader views the README on GitHub or the benchmark guide on the documentation site with a dark appearance
- **THEN** the dark chart variant is shown instead of the light one

### Requirement: Latency chart shows one cached-read value

The latency chart SHALL show a single cached-read value for both deployments, measured as the median of cache hits without concurrent writes on a CPU that was busy immediately before measurement.

#### Scenario: A maintainer regenerates the chart

- **WHEN** the chart is regenerated
- **THEN** it shows one cached-read bar labelled for either deployment, whose value does not depend on CPU idle time before measurement

### Requirement: Latency chart is regenerated from benchmark measurements

A repository command SHALL regenerate both latency chart variants and their accessible descriptions in the README and benchmark guide from current benchmark measurements.

#### Scenario: A maintainer refreshes the chart

- **WHEN** a maintainer runs the chart regeneration command with a configured real deployment
- **THEN** both variants and the documents' accessible descriptions show the new measurements
