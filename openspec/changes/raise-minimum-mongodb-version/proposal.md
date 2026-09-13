## Why

The change-stream coherency requirement currently pins the minimum supported MongoDB server version at 6.0, the version that introduced `show_expanded_events`. Every CI and local integration run already exercises MongoDB 8.0 (via `mongo:8.0.4-noble` testcontainers), so 6.x and 7.x are unsupported in practice: nothing verifies the library against them. Advertising support for versions the project never tests is misleading and risks a false sense of compatibility for callers on 6.x/7.x. Pinning the documented minimum to the version actually under test is a small, mechanical correction with no functional motivation beyond that.

## What Changes

- Raise the minimum supported MongoDB server version from 6.0 to 8.0. **BREAKING**: a server running MongoDB 6.x or 7.x, previously accepted, now fails the startup check that already exists for pre-6.0 servers.
- Update the `change-stream-coherency` requirement text and its "server cannot provide expanded events" scenario to reference 8.0 instead of 6.0.
- Update the `MINIMUM_SERVER_VERSION` constant and its startup error message in both the synchronous and asynchronous stream implementations.
- Document the minimum supported MongoDB server version in the README as a stated prerequisite.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `change-stream-coherency`: the minimum MongoDB server version a manager will start against changes from 6.0 to 8.0.

## Impact

- `src/mongo_client_cache/synchronous/streams.py` and `src/mongo_client_cache/asynchronous/streams.py`: `MINIMUM_SERVER_VERSION` and the associated error message.
- `tests/synchronous/test_streams.py` and `tests/asynchronous/test_streams.py`: the existing below-minimum-version test case already uses a version array well under 8.0, but a new case is needed to cover a server between the old and new minimum (7.x), which was previously accepted and must now be rejected.
- `openspec/specs/change-stream-coherency/spec.md`: the requirement text and scenario naming the version number.
- `README.md`: no existing version requirement is documented; add one.
