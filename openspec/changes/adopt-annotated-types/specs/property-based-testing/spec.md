# Spec Delta

## ADDED Requirements

### Requirement: Public numeric configuration accepts its annotated domain

The repository SHALL verify, using values Hypothesis derives from the constrained aliases that annotate public numeric configuration, that construction accepts every admitted value that also satisfies the configuration's documented cross-field relationships.

#### Scenario: Generated budgets construct a configuration

- **WHEN** Hypothesis draws a shared budget and a maximum entry size from their annotation aliases, with the entry size not exceeding the budget
- **THEN** cache configuration construction succeeds

#### Scenario: An annotation admits a value that validation rejects

- **WHEN** an alias that annotates a public configuration field admits a value that construction rejects
- **THEN** the property test fails
