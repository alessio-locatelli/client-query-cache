# Spec Delta

## REMOVED Requirements

### Requirement: The supported API uses composition

**Reason**: The `cached-read-api` requirements "A cached read view accepts an existing PyMongo collection" and "Facades preserve caller-owned clients" own this contract.
**Migration**: None. Behavior is unchanged.

### Requirement: Prototype migration is explicit

**Reason**: The migration is complete, and its history belongs in archived changes and the Git log.
**Migration**: None.
