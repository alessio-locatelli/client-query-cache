## ADDED Requirements

### Requirement: Catalogue content caching is controlled by application configuration

The catalogue application SHALL select direct PyMongo or cached content reads through an application-owned deployment flag. Both modes SHALL return the expected tenant-scoped item and ordered page data. Writes and freshness-critical workflows SHALL remain direct in either mode. The example SHALL NOT require a package-level cache-enable option.

#### Scenario: Both storage selections are exercised

- **WHEN** the executable scenario requests items and pages with caching disabled and enabled
- **THEN** each mode returns the expected data for both demonstration tenants
- **AND** mutation responses use direct reads in each mode

### Requirement: Rollout selection does not change access checks

The catalogue SHALL apply its trusted identity dependency and authorization checks before storage access in both modes. Its rollout self-check SHALL verify missing identity, forbidden mutation, and tenant-selector tampering in each mode, including warmed-cache reads when enabled.

#### Scenario: Storage selection changes

- **WHEN** the self-check repeats authorized and unauthorized requests under each flag value
- **THEN** expected tenant isolation and access denials hold independently of the selection

### Requirement: The rollout guide states read consistency and availability boundaries

The canonical guide SHALL identify the direct-read concern and read preference chosen by the application, explain that eligible cache misses use majority read concern, and distinguish cache hits from server reads. It SHALL link the existing consistency guidance without promising identical freshness or availability across modes.

#### Scenario: A reader evaluates the deployment flag

- **WHEN** a reader follows the rollout guidance
- **THEN** they can identify each mode's read policy and why a cache hit, miss, or direct read has different execution and freshness behavior

### Requirement: Rollback retains stored data and closes application resources

The rollout scenario SHALL reuse one client and manager across requests within each application lifespan. It SHALL demonstrate disabled, enabled, then disabled operation over the same seeded data without resetting or migrating that data between modes. Each lifespan SHALL close its manager before its client and verify released cache resources.

#### Scenario: An enabled deployment is rolled back

- **WHEN** the enabled lifespan closes and a disabled lifespan starts over the same dataset
- **THEN** direct reads return the expected documents, including an authorized update from the enabled phase
- **AND** the closed manager reports no resident entries or bytes

### Requirement: Rollout observations use public snapshots

The scenario SHALL report public hit, miss, bypass, and resource snapshots at mode boundaries. It SHALL verify enabled reuse, a deliberate ineligible cached-view read, and unchanged cache counters during direct content reads. It SHALL distinguish direct reads from cache bypasses, and SHALL fail visibly when required evidence is missing.

#### Scenario: Cache and direct-read evidence is collected

- **WHEN** the self-check samples before and after each controlled operation
- **THEN** it demonstrates a miss, a subsequent hit, and an ordinary bypass when enabled
- **AND** direct reads leave cache outcome counters unchanged
- **AND** missing expected behavior causes a nonzero exit naming that behavior

### Requirement: Rollout operating policy stays with the application

The canonical rollout guide SHALL link the existing OpenTelemetry guide and rollback reference. It SHALL leave alert thresholds and rollout percentages to the application's operating policy.

#### Scenario: An operator adopts the example

- **WHEN** an operator reads the rollout guide extension
- **THEN** it points to the existing metrics integration and rollback contract without prescribing organization-specific thresholds or percentages
