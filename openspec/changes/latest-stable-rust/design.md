## Context

The native extension is built by Cargo and maturin on developer machines and both Linux CI architectures. Fedora packages and hosted runner defaults currently vary independently.

## Goals / Non-Goals

The root rustup file selects one stable release and components. Dependabot proposes updates weekly. This does not add an older compiler matrix or change supported wheel targets.

## Decisions

Use rustup to interpret the root selection, including on the Fedora image and hosted runners. Rust toolchain changes select Rust, Python, container and ARM64 validation. Existing automatic dependency acceptance excludes toolchain changes so a human reviews the performance and compatibility evidence.

## Risks / Trade-offs

Installing a new compiler requires network access and may increase cold CI setup time. Compiler-generated code can change performance; comparisons against main are required before accepting an upgrade.
