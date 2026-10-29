## Context

The native extension is built by Cargo and maturin on developer machines and both Linux CI architectures. Fedora packages and hosted runner defaults currently vary independently.

## Goals / Non-Goals

The root rustup file selects one stable release with the minimal profile, keeping source builds limited to compiler, standard library, and Cargo. Native quality setup installs rustfmt, Clippy, and LLVM coverage components separately. Dependabot proposes updates weekly. This does not add an older compiler matrix or change supported wheel targets.

## Decisions

Use rustup to interpret the root selection, including on the Fedora image and hosted runners. CI installs Rust only for jobs that build or check native code, while the contributor image sets the selected release as its default outside the checkout. Rust toolchain changes select Rust, Python, container and ARM64 validation. Existing automatic dependency acceptance excludes toolchain changes so a human reviews the performance and compatibility evidence.

Rust 1.99.1 Clippy denies the previous constant-sized `chunks_exact` and nested conditional forms. The native source updates use Clippy's suggested equivalents so the compiler upgrade can keep the warning-free quality gate without lint suppressions.

## Risks / Trade-offs

Installing a new compiler requires network access and may increase cold CI setup time. Compiler-generated code can change performance; comparisons against main are required before accepting an upgrade.
