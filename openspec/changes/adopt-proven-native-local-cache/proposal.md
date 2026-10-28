## Why

The completed experiment demonstrated lower CPU use for complete cached reads, but fixed percentage cutoffs prevented delivery. The user has replaced those cutoffs with acceptance of demonstrated improvements of any size, subject to discussed material trade-offs.

## What Changes

- Apply the revised acceptance policy to the preserved corrected candidate and deliver the ordinary package implementation.
- **BREAKING**: advanced process-local core and capture objects may change concrete types; supported read and inspection behavior remains governed by the existing contracts.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `process-local-cache-evaluation`: replace the minimum gain requirement with evidence-based acceptance and explicitly adopt the corrected candidate.

## Impact

The existing native extension, process-local managers, core typing, tests, performance policy, benchmark report, and changelog are affected. Shared-cache ownership continues to use its existing observer-capable implementation. No new dependency or backend configuration is introduced.
