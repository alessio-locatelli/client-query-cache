## ADDED Requirements

### Requirement: Locally captured misses preserve admission fencing

A research worker MAY capture a miss without an owner round trip. Admission SHALL reject captures spanning a processed write, namespace reset, owner replacement, database availability transition or expired upstream progress. The authoritative cache SHALL validate admission races after capture validation. Capture lifetime and transport buffers SHALL remain bounded; cancellation SHALL retain no owner capture.

#### Scenario: A previously uncached identity is written during a read

- **WHEN** the owner processes its write after local capture and before admission
- **THEN** admission rejects the captured value even if the core tracked no identity when the write arrived

#### Scenario: Progress expires and resumes during a read

- **WHEN** upstream progress expires between local capture and admission and subsequently resumes
- **THEN** the old capture remains inadmissible

#### Scenario: Validation races another write

- **WHEN** a write arrives after the owner's local-token validation
- **THEN** the core's identity capture prevents stale publication

#### Scenario: A local capture is unavailable

- **WHEN** metadata, publication slots or attachment validity cannot authorize capture
- **THEN** the worker retains the owner selection or native bypass path

### Requirement: Miss optimization evidence repeats the complete protocol

A follow-up miss study SHALL preregister fresh baseline calibration and all version 5 phases, plus the version 6 timed fault protocol. Its miss P95 and P99 upper confidence bounds SHALL satisfy the registered direct-read delta at four and eight workers in both models. Missing phases, failed capacity windows or regressed hot and active criteria SHALL prevent promotion.

#### Scenario: Cold misses pass but capacity fails

- **WHEN** fresh cold comparisons meet their limit but any required capacity window fails
- **THEN** the report retains that failure and withholds promotion
