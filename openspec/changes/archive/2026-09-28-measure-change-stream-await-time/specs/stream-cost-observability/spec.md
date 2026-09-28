# Spec Delta

## ADDED Requirements

### Requirement: Stream-poll counts describe worker calls

The existing `stream_polls` counter SHALL be labelled as the number of manager calls into change-stream iteration, not the number of MongoDB `getMore` commands. Documentation and benchmark reports SHALL NOT use it as a wire-command count. An await-time comparison SHALL obtain actual `getMore` counts from command-level observation and keep them separately labelled from the manager counter.

#### Scenario: One iteration call issues multiple commands

- **WHEN** the manager makes one change-stream iteration call and the driver issues multiple `getMore` commands before returning an event
- **THEN** `stream_polls` records the one manager call while command-level observation records each `getMore`
