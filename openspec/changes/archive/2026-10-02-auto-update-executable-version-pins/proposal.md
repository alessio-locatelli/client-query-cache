# Proposal

## Why

Executable dependencies outside package manifests remain pinned without automatic update proposals, including MongoDB images in Python and tool versions in CI and the development container. Keeping these inputs current should not require maintainers to locate every duplicate or accidentally rewrite historical benchmark evidence.

## What Changes

- Run Renovate through its official hosted app and validate configuration with its official pre-commit hook; avoid private APIs and custom bot runners.
- Retain Dependabot for supported manifests and use Renovate built-in managers and narrowly scoped regex managers for unsupported executable pins, with exclusive ownership for each dependency occurrence.
- Cover MongoDB Testcontainers images, CI uv/prek/just and interpreter selections, and Containerfile Python, PyPI tool, and Taplo download pins.
- Leave Fedora DNF packages unpinned within Fedora 44, retaining the Node.js 24 package track, because the selected bots cannot safely update their RPM pins; accept low expected development-tool breakage risk and variable package versions across rebuilds.
- Keep coupled versions, cache keys, download URLs, and checksums consistent within each update pull request while preserving exact pins and existing release tracks.
- Validate updates according to their affected consumers, including manifest-only MongoDB changes and development-container inputs.
- Exclude historical reports, test data, schema versions, the project's release version, local image labels, and published compatibility floors from the new automatic updates.

## Capabilities

### New Capabilities

- `dependency-update-automation`: Scheduled, reviewable updates of executable pins with explicit bot ownership, coupled replacements, and bounded update policies.

### Modified Capabilities

- `development-environment`: Permit Fedora DNF packages to follow repository versions while retaining pins for the base image and tools installed outside DNF.

- `continuous-integration`: Select consumer validation for executable configuration changes as well as source changes.

## Impact

Planning covers `.github/dependabot.yml`, a new Renovate configuration, `.github/workflows/`, the setup-toolchain composite action, `Containerfile`, `.python-version`, both MongoDB Python consumers, CI scope selection, focused regression tests, and contributor documentation. Renovate installation requires repository administration during implementation; this proposal does not install a bot or change repository settings. Published library APIs and declared compatibility remain unchanged.
