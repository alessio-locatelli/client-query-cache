## ADDED Requirements

### Requirement: Identity matching follows MongoDB numeric equality

Identity-guarded keys and write routing SHALL treat document identities as equal when they differ only in numeric BSON type, among 32-bit integer, 64-bit integer, double and decimal values of exactly equal value, at any nesting depth. A processed write to such a document SHALL invalidate every cached entry for an equal identity. Identities with unequal exact values SHALL remain distinct.

#### Scenario: A cached identity is written under another numeric type

- **WHEN** a read by `_id` value `1` cached a document whose stored `_id` is decimal `1`, or whose embedded `_id` holds that decimal where the read holds the integer, and the manager processes an update to that document
- **THEN** the next read cannot return the pre-invalidation cached result

#### Scenario: Unequal numeric identities stay distinct

- **WHEN** one document has the double `_id` `19.99` and another has the decimal `_id` `19.99`, and a caller reads each by its own `_id` value
- **THEN** each read returns its own document, because MongoDB does not consider the two values equal
