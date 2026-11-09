# Spec Delta

## MODIFIED Requirements

### Requirement: Memory regression workload exercises bounded cache reclamation

Memory tests SHALL exercise the production native cache core through repeated admissions, hits, eviction, invalidation, and namespace clearing at fixed namespace cardinality with a shared 4 MiB BSON budget. Identity entries with aliases and namespace-guarded entries SHALL be covered. Tests SHALL fail on declined expected admissions, absent expected hits or eviction, budget overflow, aliases that outlive their resident entries, or nonzero entry usage after clearing and closing. They SHALL observe state only through the core's public operations and snapshots.

#### Scenario: Workload exceeds cache capacity repeatedly

- **WHEN** each admission mode processes eight cycles of 1,024 fresh documents with 64 KiB payloads across two fixed namespaces, including writes and readmission
- **THEN** admissions and hits succeed, evictions occur, BSON usage stays within budget, and, for identity entries, the number of resolvable aliases equals the number of resident entries at quiescent checkpoints

#### Scenario: Namespace contents are reclaimed

- **WHEN** each workload cycle clears both namespaces with no in-flight admissions
- **THEN** entry count and BSON usage are zero and no admitted alias resolves

#### Scenario: The core closes after workload completion

- **WHEN** the workload's core is closed
- **THEN** entry count and BSON usage are zero
