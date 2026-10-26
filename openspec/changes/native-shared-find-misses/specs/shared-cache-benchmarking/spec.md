## ADDED Requirements

### Requirement: Scoped current-release optimizations retain complete evidence

A scoped optimization SHALL preregister finite matched current baseline/candidate workloads covering affected hits, misses, resource use and cache outcomes. Profiling SHALL run separately. Reports SHALL retain negative results and uncertainty. Unexplained reproducible regressions SHALL prevent promotion without user approval. Scoped evidence SHALL NOT claim requalification of historical complete protocols.

#### Scenario: A native rewrite improves finds but regresses identity reads

- **WHEN** a correction improves the targeted workload while another affected path has an unexplained reproducible regression
- **THEN** the report retains both findings and withholds promotion

#### Scenario: A serialization correction retains the owner protocol

- **WHEN** native key preparation changes while the shared protocol remains identical
- **THEN** matched comparisons cover both API models, exact hits, cold misses and existing identity paths with expected cache outcomes

## MODIFIED Requirements

### Requirement: Miss optimization evidence repeats the complete protocol

A follow-up miss study claiming complete-protocol qualification SHALL preregister fresh baseline calibration and all version 5 phases, plus the version 6 timed fault protocol. Its miss P95 and P99 upper confidence bounds SHALL satisfy the registered direct-read delta at four and eight workers in both models. Missing phases, failed capacity windows or regressed hot and active criteria SHALL prevent promotion.

#### Scenario: Cold misses pass but capacity fails

- **WHEN** fresh cold comparisons meet their limit but any required capacity window fails
- **THEN** the report retains that failure and withholds promotion
