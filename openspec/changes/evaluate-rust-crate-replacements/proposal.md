# Proposal

## Why

The native extension contains handwritten utilities and uses general-purpose defaults where established Rust crates may reduce CPU work, allocations, or maintenance. The supplied assessment identifies useful leads, but its revision and unmeasured estimates need checking against the current implementation.

## What Changes

- Evaluate the ordered candidates in `design.md` D1 and integrate qualifying substitutions in this change, rather than ending with recommendations alone.
- Adjust the evaluation policy for focused dependency substitutions; the acceptance and acquisition rules live in the delta spec.
- Retain evaluation evidence according to the delta's reporting and reproducibility requirements.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `process-local-cache-evaluation`: Proportionate evidence and qualification for focused Rust dependency substitutions, distinct from cache-core migrations.

## Impact

Potential implementation sites are `native/shared-index/src/{hash,index,local_cache,key_encoder,array,python}.rs` and `local_cache/shared.rs`. Dependency changes affect the native Cargo manifest and lockfile, subject to `deny.toml`; useful measurement tooling belongs under `research/`, with lasting evidence under `reports/rust-crate-replacements/`. Existing cache APIs and consistency specifications remain authoritative.
