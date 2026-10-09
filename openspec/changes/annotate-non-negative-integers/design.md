# Design

## Context

See [proposal.md](proposal.md). The alias module, runtime-import rule, and Ruff exemption from the type-annotations capability already exist, so this change only widens where the aliases apply.

## Decisions

### Scope is every written integer type

The rule covers every `int` written as a field, parameter, or return annotation, a type argument, a type alias, or a `cast` target. Integers whose type is only inferred, such as local variables or instance attributes initialized from literals, are out of scope: adding annotations solely to restate an inferred type would add churn without new information at any boundary.

### Classifying an integer

An integer is non-negative when every value the code produces or accepts is at least zero: counts, sizes, lengths, indexes, generations, ports, durations in whole units, bit masks, and values a native API rejects when negative before the annotated code sees them. An integer stays bare when the domain includes negative values: hashes, sort directions, signed differences, random seeds, find limits with native negative semantics, and validation inputs that accept any caller value before checking it. `PositiveInt` or `MaxAwaitTimeMs` replaces `NonNegativeInt` where validation already guarantees that narrower range.

Alternatives considered:

- Annotating inferred locals and attributes as well was rejected for the reason given under scope.
- Keeping the previous rule, which converts only ranges stated in prose, was rejected because a deleted "can be zero" comment then left a real invariant unstated.

No research is needed: annotations are postponed and `cast` targets are strings, so the change has no runtime cost.
