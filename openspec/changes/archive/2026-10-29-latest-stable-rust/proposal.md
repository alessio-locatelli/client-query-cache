## Why

Development and CI currently obtain Rust independently, so compiler changes are neither coordinated nor validated as a single toolchain update.

## What Changes

- Select the latest stable compiler in one rustup toolchain file and update it through Dependabot.
- Use that selection in development, CI and release builds, and require human review of toolchain updates.
- Remove the minimum compiler commitment while preserving the existing wheel and platform support.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `development-environment`: Select the Rust toolchain consistently in the contributor image and other environments.

## Impact

Rust setup, contributor image, dependency automation, CI scope and developer documentation change. Compiler upgrades require existing correctness and performance validation.
