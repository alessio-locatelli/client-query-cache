## ADDED Requirements

### Requirement: Shared find selection preserves exact hits and compatible reuse

Eligible nonnegative-limit shared finds SHALL use native exact hits. A definite family absence with complete publication SHALL permit local capture. Possible family membership or incomplete publication SHALL retain owner selection for the smallest covering positive-limit result, then unlimited. Invalid native state SHALL retain fallback. Negative and boolean limits SHALL retain existing behavior.

#### Scenario: Another worker requests a smaller limit

- **WHEN** one worker admits eight ordered results and another requests four with the same family
- **THEN** the second worker receives the first four results through owner selection without a MongoDB read

#### Scenario: An eligible find has no cached result

- **WHEN** publication is complete and the filter establishes no resident family member
- **THEN** it captures locally and reads MongoDB without an owner selection round trip

#### Scenario: Only the owner retains a covering result

- **WHEN** arena or index capacity prevents publication of a resident compatible result
- **THEN** workers retain owner selection and can reuse that result

### Requirement: Local find capture retains bounded cursor ownership

Locally captured find admissions SHALL preserve namespace, write, availability, progress and incarnation fences. They SHALL publish only fully consumed bounded snapshots through bounded transport, without reserving an owner capture handle. Family selection metadata SHALL remain bounded and be reclaimed with its entries and namespace.

#### Scenario: A locally captured cursor is interrupted

- **WHEN** consumption closes, fails or is cancelled before completion
- **THEN** it publishes nothing and retains no owner capture handle

#### Scenario: A write crosses local capture

- **WHEN** a processed write occurs after local capture or after token validation but before admission commits
- **THEN** the captured result cannot become a shared hit

#### Scenario: A publication failure is cleared

- **WHEN** an unpublished entry is removed while another unpublished entry remains
- **THEN** native absence remains ineligible for local miss capture

#### Scenario: Namespace and family entries disappear

- **WHEN** eviction, invalidation or namespace release removes the last relevant entry
- **THEN** its filter contributions and stale completeness references are reclaimed
