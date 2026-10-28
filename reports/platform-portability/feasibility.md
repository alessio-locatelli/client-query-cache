# Platform portability feasibility

Investigation for [issue #340](https://github.com/alessio-locatelli/client-query-cache/issues/340),
2026-10-28, initial source revision `c813ee35`. Target selection and native
qualification are recorded below. The
[installation requirements](../../docs/user/getting-started/installation.md#requirements)
are the canonical support statement.
Demand from prospective users remains unknown.

## Recommendation

The implemented first target is **Linux ARM64/glibc, for process-local and shared
caching**, following [the design](../../openspec/changes/archive/2026-10-28-support-linux-arm64/design.md). It preserves the Linux security and
shared-memory architecture and adds one architecture rather than a new OS backend.
The cost is a native ARM validation lane, a second release wheel and continuing
coverage of platform-sensitive changes. No runtime-performance benefit is claimed.

macOS/Windows process-local support is feasible through a separate import and
native-compilation boundary, but is a larger first target. A decision to retain
current support is also reasonable if the recurring validation cost is unwanted.
Neither ecosystem adoption nor these probes establish user demand. macOS/Windows process-local implementation is tracked in
[issue #357](https://github.com/alessio-locatelli/client-query-cache/issues/357).
Shared caching on those systems remains outside that ticket. musl has no support
commitment in this change.

## Process-local dependency boundary

The Python import chain is `client_query_cache.__init__` → `shared` →
`_shared.coordinator`/`_shared.attachment`. Coordinator imports `fcntl`;
attachment and `shared` register fork callbacks at import. Importing either sync
or asyncio subpackage first still initializes the root package. Their existing
lazy shared-manager exports therefore do not isolate process-local consumers.

Both managers and subpackage `CacheCore` exports now import `LocalCacheCore` from
`_shared_index`. Its Rust implementation, `native/shared-index/src/local_cache.rs`,
uses Rust collections, synchronization and PyO3, with Python callbacks from
`_core/native.py`; it has no direct dependency on the shared mapping, clock or
transport modules. However, `lib.rs` compiles those modules in ordinary builds,
and `python.rs` registers the local owner alongside Unix descriptor/socket types.
Maturin builds that single extension for every installation. A Python-only import
change is consequently insufficient.

A clean separation can retain one distribution and extension: isolate module
registration, compile Linux shared modules only for Linux, and defer shared
Python imports until those APIs are requested. Keep local constructors and class
identities intact, and report unsupported shared use explicitly. This would
remove known blockers for process-local caching on macOS and native Windows;
it would not establish support without native wheels, installation, sync/async
real-server tests and lifecycle validation on each target. Windows also lacks
`fcntl` and `os.register_at_fork`; macOS lacks the Linux `memfd` sealing and peer
credential API used here. Neither would gain shared caching from this split.
The uv development lock is Linux-scoped, so non-Linux development/test dependency
resolution also needs work. Ordinary wheel consumers do not use that lock.

A separate native package would isolate artifacts but introduce coordinated
versions and dependency selection. Reusing the private Python reference cache
would avoid Rust for local users but change the selected runtime implementation
and require performance requalification. Neither is necessary to establish a
compilation boundary; neither is recommended in this investigation.

## Initial Linux ARM64 build and runtime barriers

**Build:** No x86 assembly or architecture-specific intrinsics were found in the
native sources. Rust's `aarch64-unknown-linux-gnu` target configuration reports
64-bit pointers, little endian and 64-bit atomics. Only the x86-64 Rust standard
library is installed here, with no ARM linker/emulator or native ARM machine.
No ARM cross-build or ARM execution was performed. The release recipe uses
Maturin/Zig with `manylinux_2_28`, and publication/verification at the initial revision ran only
on `ubuntu-24.04`. ARM needs its own build, isolated wheel/sdist verification and
artifact collection before the existing approval-controlled publication step.
[Maturin documents the Linux wheel/linker requirements](https://www.maturin.rs/distribution.html).

**Runtime:** At the initial revision, `SharedCacheServer.__init__` rejected
machines other than `x86_64`; its regression test encoded that restriction. Linux ARM64 should
provide the same `memfd_create`, sealing, `/proc/self/fd`, Unix descriptor passing,
`SO_PEERCRED` and monotonic-clock facilities, subject to kernel/security policy.
That is a feasibility inference, not observed target behavior.

The mapping is page-aligned and addressed in eight-byte words. Rust documents
[`AtomicU64` size and alignment](https://doc.rust-lang.org/stable/core/sync/atomic/type.AtomicU64.html)
as eight bytes; Rust target configuration establishes atomic availability, not
interprocess correctness. `index.rs` uses native-endian words and versioned reads
with acquire/release operations and fences. `ring.rs` and `frames.rs` publish
relaxed body stores through release tails and acquire reads. No x86 ordering
primitive is used, but ARM's weaker memory ordering makes native concurrency
validation essential. Existing Loom models cover bounded in-process index/frame
schedules; they omit OS mappings and Python consumers and do not prove cross-process
mapping safety. Owner/readers are on one host; mixed-architecture mappings are
outside the deployment contract.

The first-target acceptance must exercise native mappings/seals, local ownership,
sync/async cached reads and invalidation, spawned workers, owner failure/restart,
attachment authentication and cleanup. A compiled wheel or passing import alone
is insufficient. A focused native ARM lane is available through
[GitHub's `ubuntu-24.04-arm` runners](https://github.blog/changelog/2026-01-29-arm64-standard-runners-are-now-available-in-private-repositories/);
no new OS/interpreter Cartesian matrix is needed for the feasibility study.

## Initial host evidence and limits

On Fedora Toolbx Linux x86-64, CPython 3.14.7, Rust 1.99.1:

- Imports, `CacheCore` creation/close, and sync/async manager construction/close
  with `connect=False` succeeded. Both managers used native `LocalCacheCore`.
  These probes made no database reads and did not validate change streams.
- In six fresh subprocesses, an import hook rejecting either `fcntl` or
  `client_query_cache._shared_index` prevented each of the root/sync/async public
  imports. This demonstrates coupling on the host, not target-OS execution.
- The ordinary native harness passed 64 tests, including OS-backed tests. It runs
  without the `python` feature and does not exercise the local PyO3 owner.
- All seven bounded Loom model tests passed on this host. They do not execute
  the Linux mapping or Python consumer paths.
- The host release wheel built successfully as
  `client_query_cache-0.9.1-cp314-abi3-manylinux_2_28_x86_64.whl`.
- ARM64, macOS, Windows and musl runtime environments were unavailable locally.
  These initial probes establish no target runtime support or ARM performance
  result. Subsequent hosted ARM evidence is recorded below.

Reproduce the build/native checks from this revision after normal project setup:

```bash
cargo test --locked --manifest-path native/shared-index/Cargo.toml --quiet
RUSTFLAGS='--cfg loom' cargo test --locked --release --manifest-path native/shared-index/Cargo.toml --quiet
rustc --print cfg --target aarch64-unknown-linux-gnu
CARGO_ZIGBUILD_PYTHON_PATH="$PWD/scripts/zig-linker.sh" uv run -- maturin build --release --zig --compatibility manylinux_2_28 --locked --out /tmp/agents/issue-340/wheels
```

To reproduce the import boundary, run a fresh interpreter for each entry point
(`client_query_cache`, `.synchronous`, `.asynchronous`) with a
`MetaPathFinder.find_spec` that raises `ModuleNotFoundError` for `fcntl`, then
repeat blocking `client_query_cache._shared_index`. Instantiate each manager with
a user-owned PyMongo client configured with `connect=False` for the lifecycle
probe. No platform behavior should be mocked into a support claim.

## musl boundary

musl remains Linux and may provide the required kernel facilities; it does not
solve the shared-host prerequisites. The glibc wheel cannot establish musl
compatibility. A musllinux build/tag, suitable Python and dependency artifacts,
libc binding checks and native runtime validation would be required. No specific
musl source defect was demonstrated. This investigation does not propose that
additional build and validation surface.

## Implementation qualification

The implementation covers Linux ARM64/glibc build, test and release integration
and the server platform check. The native cache implementation is unchanged.
Source review of the eight-byte mapping offsets, page alignment, little-endian
64-bit target configuration, version/fence publication and ring/frame ordering
identified no required core change. This conclusion is limited by the native
runtime evidence below; bounded models do not prove every possible interleaving.

The [native ARM64 acceptance job](https://github.com/alessio-locatelli/client-query-cache/actions/runs/40758276068/job/123066528463)
ran on `ubuntu-24.04-arm` and reported `aarch64`, CPython
`3.14.7 (main, Sep 29 2026, 15:00:05) [Clang 22.1.3 ]`. It tested source
`77ef3632551929cfd2053a791260eeeaf2484b18` through merge revision
`9cae5de7f3954ec1fb344c4896056d77f82fa866` against `c813ee35`:

- All 64 ordinary native tests passed, including OS-backed mappings.
- All 2,358 selected Python tests passed in 139 seconds. The command was
  `uv run -- pytest -q tests/core tests/synchronous tests/asynchronous tests/shared_cache tests/e2e`.
  This exercises local ownership, sync/async real-server behavior, invalidation,
  shared workers, authentication, shutdown and recovery.
- Wheel and source installations passed the existing isolated public-API/owner
  lifecycle probe. The complete job took 3 minutes 28 seconds. No compiler warnings or test warning summaries
  were reported in this lane.

[Non-publishing release verification](https://github.com/alessio-locatelli/client-query-cache/actions/runs/40758357095)
also passed on native ARM64 and x86-64 for source `77ef3632`. The jobs took
61 and 79 seconds respectively. Both native jobs installed and verified their
own wheel and source archive; neither published a package.

[Version 0.10.0 release verification](https://github.com/alessio-locatelli/client-query-cache/actions/runs/40763445975)
subsequently passed on both native architectures for source
`568c845883accbc3ef733f900551a68bb7ffe429`, including the `v0.10.0` metadata check.
The downloaded artifact set contained exactly
`client_query_cache-0.10.0-cp314-abi3-manylinux_2_28_aarch64.whl`,
`client_query_cache-0.10.0-cp314-abi3-manylinux_2_28_x86_64.whl` and one
`client_query_cache-0.10.0.tar.gz`. This validates the prepared release version;
the later linker-scope regression and benchmark-command corrections do not change
the native cache implementation.

A local smoke test of the aggregate's shell confirmed that failed, cancelled or
skipped ARM outcomes return failure for both full-Python and ARM-only selection.
Publication uses GitHub's normal success dependencies across the build matrix;
its live state-changing steps were not invoked. Public guidance now includes the
qualified target. The private cache algorithms and native layout are unchanged;
this work establishes no cross-architecture performance comparison or exhaustive
proof of shared-memory correctness. macOS, Windows and musl remain unqualified.
