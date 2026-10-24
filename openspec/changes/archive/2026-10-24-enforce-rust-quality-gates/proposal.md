# Proposal

## Why

The native extension lacks the enforced formatting, linting, and dependency checks expected of this repository. Passing Python checks does not establish the quality of Rust source or its Python bindings.

## What Changes

- Establish native quality requirements in the contributor workflow.
- Integrate the checks into local commands and pull request validation.
- Resolve violations exposed by the new gates without changing the public cache API.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `development-environment`: Rust formatting, compiler diagnostics, and dependency hygiene.
- `test-environment`: Native concurrency verification.
- `continuous-integration`: Native validation selection and ordering.

## Impact

Native crate, just recipes, contributor setup, hooks, CI, and development documentation. Development tools remain separate from published runtime dependencies.
