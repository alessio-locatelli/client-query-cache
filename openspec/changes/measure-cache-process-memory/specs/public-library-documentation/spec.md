# Spec Delta

## ADDED Requirements

### Requirement: Capacity guidance quantifies memory beyond the BSON budget

Public capacity guidance SHALL state that cache budgets bound stored and captured BSON, not process memory. It SHALL give measured examples of added process memory relative to stored BSON for large results, documents, small results, and large filters, and for concurrent partially consumed misses, naming the measured versions and conditions.

#### Scenario: An operator sizes a container memory limit

- **WHEN** an operator reads the capacity guidance for a workload with known result sizes and filter sizes
- **THEN** they can estimate the memory the cache adds beyond its configured budget and identify which workload shapes multiply it

### Requirement: Capacity guidance explains memory retained after release

Public capacity guidance SHALL explain that memory freed by eviction, cursor closure, or manager closure can remain part of the process and is reused rather than returned, so memory limits follow observed peaks. It SHALL distinguish container memory counters from process resident memory.

#### Scenario: Memory stays high after closing a manager

- **WHEN** an operator observes process memory above its pre-cache level after eviction, cursor closure, or manager closure
- **THEN** the guidance tells them whether to expect this, how it relates to the observed peak, and which counter their container limit applies to
