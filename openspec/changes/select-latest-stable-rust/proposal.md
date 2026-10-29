## Why

Native builds use whichever Rust compiler each environment provides: GitHub runner images change their preinstalled release with image updates, the contributor image installs Fedora's packages, and contributors bring their own. The crate declares a Rust 1.85 minimum that no check exercises. Compiler changes therefore reach development, CI, and releases unannounced and unvalidated.

## What Changes

- Select one exact stable Rust release in a root rustup toolchain file and compile development, CI, release, and source-distribution builds with it.
- Remove the untested minimum Rust version; only the selected release is tested and supported.
- Replace the contributor image's Fedora Rust packages with rustup defaulting to the selected release.
- Propose newer stable releases, including patch releases, through weekly Dependabot checks that run the existing native, Python, ARM64, container, and performance validation.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `development-environment`: Native builds and the contributor image use the selected Rust release.
- `dependency-update-automation`: The Rust toolchain has a weekly update cadence.
- `continuous-integration`: Toolchain changes select the affected native, Python, ARM64, and container checks.
- `performance-regression-guard`: Toolchain changes run the hot-path guard.

## Impact

Toolchain selection, crate manifest, contributor image and its check, native setup recipe, package build configuration, Dependabot configuration, CI and guard path selection, developer and installation guides. Removing the minimum version enables Clippy suggestions that require newer Rust, so three native functions change form.
