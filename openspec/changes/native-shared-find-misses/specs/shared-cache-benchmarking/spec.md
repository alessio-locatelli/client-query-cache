## MODIFIED Requirements

### Requirement: Miss optimization evidence repeats the complete protocol

Miss optimization evidence SHALL preregister matched current baseline/candidate workloads covering affected hits, misses, resource use, saturation and failure fences. Repeated timing SHALL be separate from profiling and retain uncertainty and negative results. Reproducible regressions SHALL prevent promotion without user approval. A scoped optimization SHALL NOT claim requalification of historical full-protocol results.

#### Scenario: Cold misses pass but capacity fails

- **WHEN** fresh cold comparisons meet their limit but any required capacity window fails
- **THEN** the report retains that failure and withholds promotion

#### Scenario: A scoped native selection change

- **WHEN** profiling identifies shared find selection as an avoidable boundary
- **THEN** fresh matched comparisons cover that path, existing identity paths, compatible limits and publication saturation
- **AND** historical measurements are retained without claiming their full protocol was repeated

## ADDED Requirements

### Requirement: Native find selection has independent validity checks

Native exact-find selection SHALL verify the full key and validate result bytes. Local miss authorization SHALL require a definite family absence and account for resident reusable entries not represented by native publication. Filter collisions SHALL only cause owner fallback. Existing exact-key lookup costs SHALL be preserved structurally.

#### Scenario: Family lookup encounters concurrent removal

- **WHEN** a filter contribution or selected payload is removed and its storage reused during a read
- **THEN** the reader returns a validated matching result or falls back, without decoding reclaimed data

#### Scenario: Families collide

- **WHEN** different families share an index hash or probe chain
- **THEN** equality checks prevent cross-family reuse and filter collisions can only add owner requests
