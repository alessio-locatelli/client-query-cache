# Spec Delta

## MODIFIED Requirements

### Requirement: Change-stream projection retains routing fields

The stream projection SHALL retain resume tokens and routing fields while omitting full documents and raw update descriptions. Selectively configured collections SHALL receive only bounded invalidation hints required by their enabled policies. Unconfigured collections and irrelevant operations SHALL receive no additional hint payload. No per-query or per-partition streams or event-time lookups SHALL be added.

#### Scenario: A projected change event reaches the router

- **WHEN** the database stream projects a change event
- **THEN** its resume token and routing fields remain available without fetching unnecessary full-document or update-description content

#### Scenario: A database contains mixed policies

- **WHEN** one collection enables insert partitioning, another enables count dependencies, and a third has no policy
- **THEN** only inserts for the first receive a bounded partition hint, only updates for the second receive bounded changed-field names, and the third receives routing fields only

#### Scenario: Projection cannot prove a bounded hint

- **WHEN** a required value or update description is missing, ambiguous, unsupported, or exceeds the projection bounds
- **THEN** the event carries an explicit unknown proof and its affected selective results are invalidated conservatively

#### Scenario: An update contains large values

- **WHEN** an update changes large document values or many field paths
- **THEN** the projected hint transmits bounded names or an unknown marker, without updated values, full documents, images, or additional reads

#### Scenario: A stream reopens

- **WHEN** startup retry or established-stream recovery opens a database cursor
- **THEN** it uses the same immutable collection policy projection as initial activation
