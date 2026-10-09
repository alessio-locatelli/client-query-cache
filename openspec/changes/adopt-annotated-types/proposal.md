# Proposal

## Why

Value constraints such as "positive", "nonempty", or "probability in (0, 1)" are currently either left implicit behind bare `int`, `str`, and collection annotations, or stated in trailing comments that tools cannot read. Annotation metadata from [annotated-types](https://github.com/annotated-types/annotated-types) states the same constraints once, where readers, type checkers, introspection tools, and Hypothesis's `from_type` can find them.

## What Changes

- Add `annotated-types` as a published runtime dependency.
- Add one private module of shared constrained aliases for numeric ranges and nonempty strings and collections.
- Replace prose that explains a type's constraints in `src/`, `tests/`, `benchmarks/`, and `scripts/` with these aliases. Keep prose that explains what a value means.
- Annotate public numeric configuration and snapshot fields with their ranges, and keep public dataclass annotations resolvable at runtime.
- Verify with Hypothesis that configuration accepts every built-in integer its resolved field annotations admit.
- Annotations remain metadata only. Runtime validation stays where it is today.

## Capabilities

### New Capabilities

- `type-annotations`: Conventions for expressing value constraints in annotations rather than prose, and runtime resolvability of public dataclass annotations.

### Modified Capabilities

- `property-based-testing`: Public numeric configuration accepts every built-in integer its field annotations admit.

## Impact

Static annotations change across library, test, benchmark, and script code. Public runtime behavior and the static types callers see stay unchanged. Importing the package additionally loads `annotated-types`, a one-time cost measured in the implementation commit. Package metadata and `uv.lock` gain one small pure-Python dependency, and `ruff.toml` exempts the alias module from type-checking-only import rules. Contributor guidance in `AGENTS.md` records the convention. User documentation, the changelog, and Context7 rules need no change because the public contract is unchanged. Runnable examples are out of scope.
