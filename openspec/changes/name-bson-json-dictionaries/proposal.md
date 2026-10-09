# Proposal

## Why

Tests and benchmarks annotate BSON documents and JSON objects as `dict[str, Any]` or `dict[str, object]`, the same spellings used for keyword-argument bundles and option dictionaries. A reader cannot tell a document from an options bundle, and the `Any`-valued document sites get no value checking from mypy.

## What Changes

- Add object-valued BSON document and JSON object aliases to the shared alias module.
- Annotate BSON documents and JSON objects in `tests/` and `benchmarks/` with these aliases, and narrow values where mypy then requires it.
- Leave keyword-argument bundles, option dictionaries, read-only `Mapping` parameters, and all of `src/` unchanged.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `type-annotations`: Dictionary annotations of BSON documents and JSON objects use shared object-valued aliases.

## Impact

Annotations in `tests/` and `benchmarks/` change, together with the narrowing assertions the stricter value type requires. Library code, runtime behavior, dependencies, and public documentation are unchanged. This change builds on the alias module and the `type-annotations` capability introduced by `adopt-annotated-types`, and must be applied and archived after it.
