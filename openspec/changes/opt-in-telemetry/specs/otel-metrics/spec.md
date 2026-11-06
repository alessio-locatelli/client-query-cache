## ADDED Requirements

### Requirement: Registration requires enabled telemetry

Registration SHALL reject a disabled statistics source with `CacheConfigurationError` directing the caller to `enable_telemetry=True`, before creating any instrument. Registration SHALL NOT enable collection implicitly, allocate collection state, or request owner diagnostics. Enabled sources SHALL retain the instrument and collection contracts of this capability.

#### Scenario: A disabled source is registered

- **WHEN** a caller registers a disabled process-local manager, advanced core, or shared manager
- **THEN** registration raises the configuration error and the supplied meter receives no instruments

#### Scenario: A source is enabled before registration

- **WHEN** a caller registers an enabled source
- **THEN** instruments use its collected observations without changing its collection policy
