# Design

## Context

See [proposal.md](proposal.md) and the two delta specs. `CacheCoreConfig.__post_init__` in `_core/manager.py` and `LagCaptureWindowConfig.__post_init__` in `_core/stream_cost.py` currently compare values before checking their runtime types. A local construction check accepted NaN in both budget fields and all three lag fields; positive float budgets and an infinite shared budget were also accepted. These observations establish input-validation defects, not a leak under valid defaults.

## Goals / Non-Goals

Validate at the existing configuration ownership boundary. Do not introduce coercion, arbitrary maximum budgets, per-read validation, or a general schema-validation dependency.

## Decisions

Check `type(value) is int` for every numeric field before any range or cross-field comparison in its configuration object. Name the field in `CacheConfigurationError`. Keep explicit local checks rather than introducing a validation framework for five fields in two existing classes. Retain existing relationships after type validation; public guidance and affected Context7 rules must agree with the delta contracts.

`isinstance(value, int)` would accept booleans and integer subclasses whose overloaded comparisons could defeat the same invariants. Coercion could silently truncate values and conceal mistakes. A third-party validator adds a dependency and conversion policy for a constant-size check. Exact built-in types deliberately tighten invalid-input compatibility. No research or prototype is necessary: the local reproduction and existing maximum-await-time validation establish the relevant pattern.

Validation is constant work once per configuration; admission, eviction and telemetry recording need no changes. Existing LRU tests already check bounded eviction for valid integers. Extend their input coverage rather than constructing a runaway-memory test or duplicating internal LRU validation.

## Risks / Trade-offs

- Applications using integer subclasses or integral floats will receive an earlier library error. Document the exact built-in-integer contract without claiming those inputs were previously supported.
- Invalid types can mask invalid relationships. Checking all types first makes the error boundary deterministic and avoids incidental `TypeError` from comparisons.
- The lag fields are adjacent to the budget finding but independently affect bounded telemetry. Cover each field's type and valid zero-separation boundary in its existing tests.
