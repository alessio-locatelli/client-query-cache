# Design

## Context

See [proposal.md](proposal.md) for motivation and the linked feasibility report
for source traces and probe results. **Status: proposed; target and design await
maintainer approval under issue #340.** Implementation must not start beforehand.

The local cache already uses the bundled Rust extension. Its shared backend uses
Linux kernel facilities, while the Python server rejects non-x86-64 machines.
An ARM port can reuse that backend; a non-Linux local-only port needs both Python
import isolation and conditional native compilation. Target runtime behavior has
not yet been measured.

## Goals / Non-Goals

Use the existing public contracts and same-host security boundary. Do not add a
backend, change shared-memory ordering, restore the Python reference core as a
fallback, or promise performance parity between architectures. No migration of
cached state is needed because owner state is ephemeral.

## Decisions

### Reuse the Linux backend on little-endian ARM64

This is the recommended first target because it retains Linux descriptor passing,
sealing and peer authentication, and the target has 64-bit atomics/pointers.
It avoids the import/build split needed for macOS/Windows but introduces another
native validation and wheel artifact to maintain. Keep the native layout and
acquire/release protocol; accept `aarch64` in the Python platform guard only with
the target gate below.

Alternatives:

- **Local-only macOS or Windows:** enables desktop use without a shared backend,
  but requires native compilation boundaries, lazy Python exports, target wheels
  and native lifecycle/database validation. Actual target behavior is unknown.
  No further research is required to exclude these from this bounded change;
  issue #340's report records the feasibility boundary.
- **ARM local-only:** reduces initial shared-runtime validation, but leaves
  users on the same Linux host with architecture-dependent cache features and
  still needs an ARM build/release lane. Shared correctness is unknown, so the
  acceptance task resolves it before committing to both modes; local-only is
  not an automatic fallback if it fails.
- **Keep current platforms:** incurs no ongoing CI/release cost and is valid
  given unknown demand, but enables no new deployment environment. No technical
  investigation is needed to choose it instead during approval.

### Qualify on native hardware with a bounded CI expansion

Add one `ubuntu-24.04-arm` acceptance job using the repository interpreter and
locked dependencies, after applicable quality checks. Reuse existing test suites
for native mappings, Python local ownership, real-server sync/async reads,
invalidation, cross-process sharing, owner recovery, authentication and cleanup.
Do not multiply the Python compatibility matrix or rerun architecture-independent
Loom exploration there. ARM image/tool/dependency availability remains unknown
until this lane runs; task 2.1 owns that evidence.

Cross-compilation is a useful build diagnostic but cannot exercise ARM ordering,
Linux mapping protections or PyMongo integration. Emulation can help reproduce
failures but does not replace native acceptance. Neither alternative needs a
separate prototype before choosing native validation.

### Build and verify release artifacts per architecture

Reuse `just verify-release` in architecture-isolated jobs for x86-64 and ARM64 in
manual verification and publication. Each job verifies its own wheel and source
build, outside the checkout, with isolated dependency installation. Retain one
sdist from the x86-64 job when collecting artifacts; collect both verified wheels.
The existing publishing approval and credentials boundary follows an aggregate
success dependency. Do not attempt to install an ARM wheel on the x86-64 runner
or publish a partial set after a failed/cancelled lane.

A cross-built artifact assembled in one job saves runner setup but adds complexity
and still needs native verification. Two isolated native builds reuse the current
recipe, at the cost of another build/install. Tool availability is resolved by
task 2.2; no custom wheel validator or packaging dependency is justified.

## Risks / Trade-offs

- Weaker memory ordering may expose bugs absent on x86-64 → inspect atomic layout
  and version/fence invariants, run existing concurrency models once, and exercise
  the native cross-process suite. Passing tests provide bounded evidence, not a
  proof. A required ordering/layout redesign returns for approval.
- Native runners, Zig, dependency wheels or MongoDB images may fail on ARM →
  investigate within the acceptance tasks; do not advertise support until resolved.
- Recurring cost increases by one focused runtime lane and one artifact lane →
  preserve existing path scopes, quality prerequisites and architecture-specific
  caches; record observed job duration before acceptance.
- An actual runtime fix could regress existing users → if runtime algorithms or
  test execution change, use repeated matched comparisons against `main` on the
  same architecture and interpreter, separating existing from new tests. An
  architecture guard/release-only change has no cached-read hot-path effect.

## Migration Plan

After approval, qualify the target and update canonical installation guidance and
Context7 in the same implementation. Record native runner architecture, interpreter,
revision and artifact results. If qualification is blocked, keep support unchanged
and record the concrete scope/blocker under issue #340 before any closure. Do not
silently substitute a different target or reduce cache modes. Rollback removes
ARM advertising and its wheel from a future release; existing x86-64 behavior is
unaffected.
