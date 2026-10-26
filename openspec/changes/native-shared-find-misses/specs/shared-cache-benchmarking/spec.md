## ADDED Requirements

### Requirement: Scoped current-release optimizations retain complete evidence

A scoped optimization SHALL preregister finite matched current baseline/candidate workloads covering affected hits, misses, resource use and cache outcomes. Profiling SHALL run separately. Reports SHALL retain negative results and uncertainty. Unexplained reproducible regressions SHALL prevent promotion without user approval. Scoped evidence SHALL NOT claim requalification of historical complete protocols.

#### Scenario: A native rewrite improves finds but regresses identity reads

- **WHEN** a correction improves the targeted workload while another affected path has an unexplained reproducible regression
- **THEN** the report retains both findings and withholds promotion

#### Scenario: A serialization correction retains the owner protocol

- **WHEN** native key preparation changes while the shared protocol remains identical
- **THEN** matched comparisons cover both API models, exact hits, cold misses and existing identity paths with expected cache outcomes
