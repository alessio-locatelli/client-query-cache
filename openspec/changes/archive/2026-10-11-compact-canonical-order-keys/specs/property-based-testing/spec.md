# Spec Delta

## ADDED Requirements

### Requirement: Compact canonical keys preserve legacy equality classes

The repository SHALL verify, with Hypothesis-generated recursive BSON-like inputs drawn from a collision-prone value domain, that two inputs receive equal compact canonical keys exactly when a test-only copy of the previous canonicalization algorithm gives them equal keys. Generation SHALL cover unordered, order-sensitive, discriminator, and scalar find filter key builders, including canonical subtrees nested inside order-sensitive wrappers.

#### Scenario: A generated batch of inputs is keyed both ways

- **WHEN** Hypothesis generates a batch of inputs from a small domain of mappings, sequences, bools, integers, doubles, 64-bit integers, decimals, strings, and `None`, and keys each input with both algorithms through the same builder
- **THEN** the pairs of inputs with equal keys are the same under both algorithms, and either both algorithms reject an input as uncanonicalizable or neither does

#### Scenario: A generated compact key is canonicalized again

- **WHEN** Hypothesis generates an input and canonicalizes its compact key a second time, alone or wrapped in an order-sensitive tuple
- **THEN** the second canonicalization returns the same key object, or a wrapper that references it
