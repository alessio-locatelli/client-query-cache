# Proposal

## Why

The API introduction incorrectly calls every async read a coroutine, and deployment guidance lists native cursor bypasses as cache exceptions. Introductory positioning and ownership explanations also obscure the practical consistency boundaries.

## What Changes

- Correct the contradictory guidance and make execution versus cache admission explicit.
- Replace absolute production positioning with concrete verification evidence and prioritize application-facing ownership and integration cautions.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. Existing public-documentation requirements already require accurate contracts and supported claims; `skip_specs: true` records this documentation-only correction.

## Impact

README, API reference, cached-read and consistency guides, deployment guidance, example catalogue and Celery guide, and repository-only architecture documentation. Library behavior and dependencies are unchanged.
