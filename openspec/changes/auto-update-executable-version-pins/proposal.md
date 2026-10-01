# Proposal

## Why

Executable dependencies outside package manifests remain pinned without automatic update proposals, including MongoDB images in Python and tool versions in CI and the development container. Keeping these inputs current should not require maintainers to locate every duplicate or accidentally rewrite historical benchmark evidence.

## What Changes

- Retain Dependabot for supported manifests and introduce narrowly scoped Renovate custom managers for unsupported executable pins, with exclusive ownership for each dependency occurrence.
- Cover MongoDB Testcontainers images, CI uv/prek/just and interpreter selections, and Containerfile RPM, Python, PyPI tool, and Taplo download pins.
- Keep coupled versions, cache keys, download URLs, and checksums consistent within each update pull request while preserving exact pins and existing release tracks.
- Validate updates according to their affected consumers, including manifest-only MongoDB changes and development-container inputs.
- Exclude historical reports, test data, schema versions, the project's release version, local image labels, and published compatibility floors from the new automatic updates.

## Capabilities

### New Capabilities

- `dependency-update-automation`: Scheduled, reviewable updates of executable pins with explicit bot ownership, coupled replacements, and bounded update policies.

### Modified Capabilities

- `continuous-integration`: Select consumer validation for executable configuration changes as well as source changes.

## Impact

Planning covers `.github/dependabot.yml`, a new Renovate configuration, `.github/workflows/`, the setup-toolchain composite action, `Containerfile`, `.python-version`, both MongoDB Python consumers, CI scope selection, focused regression tests, and contributor documentation. Renovate installation requires repository administration during implementation; this proposal does not install a bot or change repository settings. Published library APIs and declared compatibility remain unchanged.
