# Proposal

## Why

The current-release investigation for [#341](https://github.com/alessio-locatelli/client-query-cache/issues/341) identifies duplicate Python query serialization on shared find misses. The user directs moving measured slow work into Rust. The rejected native selection prototypes and their performance failures remain in `reports/shared-worker-cache/current-costs/native-trials.md`.

## What Changes

Move shared find key encoding into Rust and reuse one query traversal for both required keys. Preserve the existing owner protocol and documented cache behavior. Validate the correction through the registered current-release comparison.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `shared-worker-cache`: portable shared find key preparation and bounded reuse.
- `shared-cache-benchmarking`: evidence for scoped current-release corrections.

## Impact

Native Python bindings, shared key cache and cursor adapters, differential wire tests, internal architecture guidance and benchmark evidence. No public setting or dependency is introduced.
