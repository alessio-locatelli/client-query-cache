# Spec Delta

## ADDED Requirements

### Requirement: Public numeric configuration accepts its annotated domain

The repository SHALL verify, using strategies Hypothesis derives from the runtime-resolved field annotations of the cache and lag-window configuration dataclasses, that construction accepts every built-in integer those annotations admit that also satisfies the configuration's documented cross-field relationships.

#### Scenario: Generated budgets construct a configuration

- **WHEN** Hypothesis draws a shared budget and a maximum entry size from their resolved field annotations, with the entry size not exceeding the budget
- **THEN** cache configuration construction succeeds

#### Scenario: A field annotation admits a value that validation rejects

- **WHEN** a configuration field's annotation admits a built-in integer that construction rejects
- **THEN** the property test fails
