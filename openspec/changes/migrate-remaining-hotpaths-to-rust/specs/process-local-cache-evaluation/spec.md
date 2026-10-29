# Spec Delta

## ADDED Requirements

### Requirement: Integrated development checks precede long acquisitions

Native internal replacements SHALL pass focused correctness cases and a simplified end-to-end acquisition through ordinary library construction before any multi-hour benchmark campaign. The simplified acquisition SHALL be bounded to five minutes, exercise affected execution models, verify values and cache outcomes, and expose setup or cleanup failures. Its timings SHALL NOT qualify retention.

#### Scenario: A capture replacement passes only its isolated accumulator tests

- **WHEN** a long confirmation campaign is about to start
- **THEN** it waits for a bounded real-database cold read, completed admission, and subsequent hit through the installed library

#### Scenario: Development acquisition exceeds its deadline

- **WHEN** setup, execution, or teardown exceeds the five-minute bound
- **THEN** the run fails visibly and the cause is resolved before expensive acquisition begins

### Requirement: Internal migrations have independently attributable decisions

A change evaluating multiple native internal replacements SHALL register a target and disposition for each component. It SHALL compare each retained stage with its predecessor and the final ordinary build with frozen current main. One component's gain SHALL NOT qualify another component lacking a demonstrated benefit. Negative or inconclusive components SHALL preserve the working implementation and their evidence.

#### Scenario: Capture improves while query preparation does not

- **WHEN** only capture has a confirmed registered benefit
- **THEN** capture is retained, query preparation remains unchanged, and both outcomes appear in the report

#### Scenario: Earlier optimizations change the next bottleneck

- **WHEN** the preceding retained stage already eliminates the cost targeted by another replacement
- **THEN** the later disposition uses that stage as its control rather than claiming the earlier gain again

### Requirement: Staged acquisition avoids repeated full campaigns

Each candidate SHALL use one matched benchmark lasting less than thirty minutes, including all repetitions and teardown. The combined retained build SHALL run the existing multi-hour benchmark campaign once against frozen main. Routine per-candidate full campaigns and automatic uncertainty campaigns SHALL NOT be required. Further acquisition SHALL identify a concrete failure, invalid result, correction, or unresolved adverse signal that requires it.

#### Scenario: Three candidates pass their short comparisons

- **WHEN** the combined ordinary build is ready for broad performance validation
- **THEN** one existing full campaign compares that build with main rather than running it separately for each component

#### Scenario: A comparison remains noisy

- **WHEN** the short benchmark reaches its declared budget without a clear result
- **THEN** its uncertainty is retained and does not automatically start another acquisition cohort
