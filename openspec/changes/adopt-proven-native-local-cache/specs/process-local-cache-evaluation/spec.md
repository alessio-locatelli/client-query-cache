## REMOVED Requirements

### Requirement: Material gains use the agreed thresholds

**Reason**: The user replaced fixed minimum gains with evidence-based acceptance.
**Migration**: Apply the proven-gains requirement below; preserve historical benchmark registration.

## ADDED Requirements

### Requirement: Proven gains qualify regardless of percentage

Native retention SHALL accept a stable improvement in a predeclared complete public-operation or equal-residency resource metric when repeated matched measurements distinguish it from noise. No minimum percentage SHALL apply. Correctness failures SHALL block retention; material adverse trade-offs SHALL require discussion and a documented decision. Isolated helper timings SHALL NOT establish a complete-operation benefit.

#### Scenario: A small improvement is established

- **WHEN** repeated matched measurements establish a 0.5% improvement beyond uncertainty and no material adverse trade-off remains unresolved
- **THEN** its size alone does not prevent native retention

#### Scenario: Only key preparation improves

- **WHEN** a native helper is faster but no registered complete-operation or resource improvement is established beyond noise
- **THEN** the helper timing alone does not qualify the candidate

#### Scenario: Memory is the qualifying benefit

- **WHEN** a registered memory workload establishes a saving with equal retained entries and BSON
- **THEN** the report identifies memory as the benefit without claiming a read speedup

## MODIFIED Requirements

### Requirement: Regressions require explicit approval

Every reproducible runtime, resource, or existing-test slowdown SHALL be investigated and corrected or receive explicit user approval before native retention. A gain in another metric SHALL NOT waive this rule. Inconclusive control results SHALL remain visible and SHALL NOT be described as proof of no regression.

#### Scenario: Memory improves while small hot reads slow down

- **WHEN** a candidate establishes a memory improvement but reproducibly increases small-read latency
- **THEN** it remains unqualified unless the user explicitly approves that measured trade-off
