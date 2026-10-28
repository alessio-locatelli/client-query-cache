# Platform portability feasibility

Investigation for [issue #340](https://github.com/alessio-locatelli/client-query-cache/issues/340),
2026-10-28, source revision `c813ee35`. This report proposes a target; it does not
extend the [supported configurations](../../docs/user/getting-started/installation.md#requirements).
Demand from prospective users remains unknown.

## Recommendation

Start with **Linux ARM64/glibc, for process-local and shared caching**, subject to
approval of [the proposed design](../../openspec/changes/support-linux-arm64/design.md)
and successful native ARM64 validation. It preserves the Linux security and
shared-memory architecture and adds one architecture rather than a new OS backend.
The cost is a native ARM validation lane, a second release wheel and continuing
coverage of platform-sensitive changes. No runtime-performance benefit is claimed.

macOS/Windows process-local support is feasible through a separate import and
native-compilation boundary, but is a larger first target. A decision to retain
current support is also reasonable if the recurring validation cost is unwanted.
Neither ecosystem adoption nor these probes establish user demand. Unselected
platform work remains within the investigation context of issue #340, without a
support commitment or implementation follow-up in this change.

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

## Linux ARM64: build and runtime barriers

**Build:** No x86 assembly or architecture-specific intrinsics were found in the
native sources. Rust's `aarch64-unknown-linux-gnu` target configuration reports
64-bit pointers, little endian and 64-bit atomics. Only the x86-64 Rust standard
library is installed here, with no ARM linker/emulator or native ARM machine.
No ARM cross-build or ARM execution was performed. The release recipe uses
Maturin/Zig with `manylinux_2_28`, and publication/verification currently run only
on `ubuntu-24.04`. ARM needs its own build, isolated wheel/sdist verification and
artifact collection before the existing approval-controlled publication step.
[Maturin documents the Linux wheel/linker requirements](https://www.maturin.rs/distribution.html).

**Runtime:** `SharedCacheServer.__init__` explicitly rejects machines other than
`x86_64`; its regression test also encodes that restriction. Linux ARM64 should
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

## Evidence and limits

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
- ARM64, macOS, Windows and musl runtime environments were unavailable. No target
  wheel, target database run, ARM performance result or new supported platform is
  established by this report.

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
