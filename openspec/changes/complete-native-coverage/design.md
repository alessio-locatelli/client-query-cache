# Design

## Context

See proposal.md for scope and issue ownership. The extension is a Linux `cdylib` built by maturin. Rust unit tests, Loom models, and Python shared-cache tests already exist. Native static checks have a dedicated CI tier.

## Decisions

### Combine native and Python execution with LLVM instrumentation

Use cargo-llvm-cov's official [external-tests workflow](https://github.com/taiki-e/cargo-llvm-cov#get-coverage-of-external-tests): capture `show-env --sh`, evaluate it only after confirming success, clean prior measurements, build and execute the native test binary and extension, then report. Reuse compiled dependencies while clearing stale profiles and crate artifacts. Run Loom separately because its substituted atomics do not represent production execution.

Native-only coverage is simpler but misses binding bodies. Running the whole MongoDB suite again costs more than selecting its native consumers. Start with container-free `tests/shared_cache` and expand selection only where real behavior requires it. Task 1.1 owns verification of the complete source population and combined report; no separate research project is needed.

### Isolate the instrumented Python installation

Build the root mixed project using `uv run --isolated --only-group build -- maturin build --compatibility linux --locked`. Omitting `--manifest-path` is deliberate: passing the nested Cargo manifest selects the standalone crate metadata instead of the root Python package. Use uv's selected Python for PyO3 explicitly; system Python discovery can select an interpreter without a linkable library.

Install the wheel into a temporary venv under `/tmp/agents/`, with test dependencies exported from the committed uv lockfile. Use copy linking across filesystem boundaries. Call that venv's Python directly for pytest. Do not let uv replace the instrumented wheel or alter the ordinary editable environment.

Using `maturin develop` is shorter but replaces the contributor's active extension; installing into the normal environment also risks reusing an uninstrumented wheel. The isolated prototype exercised the real binding bodies successfully. No additional isolation research is necessary.

### Keep the coverage population explicit

Pin cargo-llvm-cov through the existing justfile version/update mechanism and provision LLVM tools matching rustc. Stable line/function coverage does not prove branch coverage. Do not introduce nightly, source exclusions, or production test seams solely to manufacture a green percentage.

An exploratory report using the 44 native unit tests and 185 container-free shared-cache tests measured 94.50% lines and 86.35% functions. That population included inline native tests and emitted a mismatched-function warning, so it is diagnostic evidence rather than an acceptance baseline. Experimental direct binding cases improved execution but did not eliminate generated-code, syscall-error, and defensive-path gaps. Establish a warning-free, production-only denominator before comparing percentages.

Inspect missed generated PyO3 spans rather than assuming they are ordinary executable functions. Stable coverage exclusion support is limited; Rust's attribute stabilization is tracked in [rust-lang/rust#134749](https://github.com/rust-lang/rust/issues/134749). This tracking issue does not establish that a particular binding span is untestable. Task 1.2 requires a reproduction and source-level justification before any exception.

### Remediate behavior before making the CI gate required

Add real boundary and lifecycle cases for invalid layout/descriptor inputs, detached readers, closed rings, payload token access, echo framing, and full-duplex relay counters and EOF. Use meaningful I/O failure injection where error paths are reachable. Remove a defensive branch only after tracing all producers and callers and proving its invariant from code/specifications. Compare runtime performance with main for any production refactor.

Excluding whole production files or lowering the threshold would conceal untested behavior and is rejected. Creating test seams can improve observability but can also affect hot paths or expand APIs; task 1.2 must keep those tradeoffs explicit. Once the target is met, integrate coverage after native static validation without rerunning interpreter-independent work in each Python lane.

## Risks / Trade-offs

- Proc-macro spans and separate build configurations can distort aggregation: reconcile LLVM warnings and validate the measured source set.
- Syscall failures can be resource-dependent: prefer reproducible real error conditions; identify unreachable paths instead of adding impossible mocks.
- Instrumentation and tool setup add CI cost: reuse dependencies and the existing executable cache, while keeping profiles fresh.
