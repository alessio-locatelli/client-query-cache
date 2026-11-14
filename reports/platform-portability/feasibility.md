# Platform boundaries for native caching

The October 2026 investigation for [#340](https://github.com/alessio-locatelli/client-query-cache/issues/340)
started at `c813ee35`. Linux ARM64/glibc preserves the Linux shared-memory and
security architecture. Current support is maintained in
[installation requirements](../../docs/user/getting-started/installation.md#requirements).
This record explains constraints on considering another OS.

## Process-local dependency boundary

The Python import chain is `client_query_cache.__init__` → `shared` →
`_shared.coordinator`/`_shared.attachment`. Coordinator imports `fcntl`;
attachment and `shared` register fork callbacks at import. Importing either sync
or asyncio subpackage first still initializes the root package. Their existing
lazy shared-manager exports therefore do not isolate process-local consumers.

Managers and subpackage `CacheCore` exports import `LocalCacheCore` from
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

A separate native package would isolate artifacts but require coordinated
versions and dependency selection. Conditional compilation and lazy shared
imports can preserve one distribution without restoring the removed Python
engine.

## Shared-memory portability constraints

The mapping uses page-aligned eight-byte words, native-endian atomics and
acquire/release version checks. ARM64 target metadata establishes atomic
availability, not interprocess correctness. Loom models omit OS mappings and
Python consumers; native target validation must cover those paths.

Native ARM64 qualification at `77ef3632551929cfd2053a791260eeeaf2484b18`
exercised mappings, local ownership, sync/async reads and invalidation, spawned
shared workers, authentication and lifecycle recovery. The [recorded job](https://github.com/alessio-locatelli/client-query-cache/actions/runs/40758276068/job/123066528463)
and [release verification](https://github.com/alessio-locatelli/client-query-cache/actions/runs/40758357095)
provide target execution evidence, not cross-architecture performance evidence.
macOS/Windows process-local work is tracked in [#357](https://github.com/alessio-locatelli/client-query-cache/issues/357);
shared support there would need a separate design.

musl may provide Linux kernel facilities, but glibc wheels cannot establish
compatibility. A musllinux build, matching dependency artifacts, libc binding
checks and native execution would be needed. No musl source defect or demand
result was demonstrated by this investigation.
