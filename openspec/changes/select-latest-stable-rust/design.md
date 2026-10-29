## Context

Cargo, maturin, and cargo-zigbuild compile the extension in editable installs, CI jobs, release wheels, and source-distribution builds. All GitHub-hosted runners used by the workflows ship rustup proxies. Fedora 44 packages both its own Rust build and rustup 1.29.0.

## Goals / Non-Goals

Goals: one compiler release everywhere, automatic proposals for each stable release, unchanged wheel targets, and no Rust installation in jobs that compile nothing.

Non-goals: testing other compiler releases or changing dependency acceptance automation.

## Decisions

### Selection file

A root `rust-toolchain.toml` pins `channel` to an exact release with the minimal profile. Rustup's proxies read it in the checkout and in the unpacked source distribution, so no workflow, recipe, or build script repeats the version.

- `channel = "stable"`: no maintenance, but unreproducible and invisible to Dependabot. Rejected.
- Listing `rustfmt`, `clippy`, and `llvm-tools-preview` in the file: one list, but every Python lane, release build, and user source build downloads them. Rejected; `just setup-rust` adds them with `rustup component add`, which rustup already makes idempotent.
- Cargo `rust-version`: declares a floor rather than selecting a compiler, and implied support for a release nobody tests. Removed without replacement.

`just setup-rust` builds the Cargo quality tools with `cargo +<selected release> install`. Without `+`, Cargo warns that the toolchain file implicitly selected the compiler; running the install outside the checkout would avoid the warning but build the tools with whatever default toolchain the environment has.

The source distribution includes the file so that a source build with rustup uses the tested release; source builders without rustup still use their own compiler, unsupported but not blocked.

### CI provisioning

Jobs that compile native code opt into a `rust` input of the shared setup action, which runs `rustup toolchain install --no-self-update` in the checkout; `just setup-rust` runs the same command for native quality jobs and contributors. Prek, formatting, documentation, and container jobs install no Rust.

- Letting the first Cargo call auto-install the selection: no setup at all, but rustup 1.29.2 warns on every proxy auto-install, and a runner without rustup would silently use its own Cargo instead of failing. Rejected.
- The same step inlined in each job: repeats the command and its rationale in a dozen places. Rejected.
- `actions-rust-lang/setup-rust-toolchain`: does what one rustup command does, but also enables a dependency cache and exports Cargo settings such as `CARGO_PROFILE_DEV_DEBUG=0` and `CARGO_INCREMENTAL=0` unless each is overridden. Rejected.

The performance guard builds its base revision in a separate worktree. On a toolchain update, that revision still selects the previous release, which rustup's proxy installs during the captured base build. Provisioning it separately would duplicate that behavior inside the Python harness, so no further work is planned.

### No CI toolchain cache

Each compiling job downloads the minimal toolchain instead of restoring it from the Actions cache. Measured on 2026-10-29, installation took a median 8.2 s on x86-64 and 5.2 s on ARM64; restoring a cached toolchain took 4.4 s and 2.1 s, saving about 4 s and 3 s per job.

- Caching: saves roughly one minute of runner time and a few seconds of elapsed time per full pull request run. But pull request caches are restored only by later runs of the same pull request, and 88 of the last 200 validation runs were first runs; each pull request would add about 345 MiB to caches that already exceed the repository's 10 GB limit, evicting other entries; and saving needs a designated job per architecture. A shared cache would need a new workflow on `main`. Rejected.

`docs/development/ci-validation-caches.md#rust-toolchain-downloads` records the full measurements, method, and revisit conditions; no further work is planned.

### Contributor image

The image installs gcc and Fedora's `rustup` package, runs `rustup-init` with the minimal profile and the selected release as its default (read with Python's `tomllib`), and makes `RUSTUP_HOME` and `CARGO_HOME` writable by every container user so that the contributor's host account can install newer selections and components. Anything running in the container can then modify the toolchain, which suits a single-contributor image.

- Fedora's `rust` packages: updated independently of the selection and lacking the LLVM tools component. Rejected.
- A read-only toolchain: every weekly update would require an image rebuild. Rejected.
- The contributor's home rustup: no default toolchain outside the checkout and conflicts with host installations. Rejected.

`just setup-rust` starts with `uv python install`, which rewrites a marker in the interpreter directory even when the interpreter is present, so the uv interpreter directory is writable too.

Fedora's rustup 1.29.0 prints a spurious settings-file warning during `rustup-init`, documented with its upstream and Fedora tickets in `CONTRIBUTING.md`.

### Updates

Dependabot's `rust-toolchain` ecosystem checks weekly, independently of the monthly Cargo schedule, and keeps the repository's seven-day cooldown, which delays each proposal by a week in exchange for time to notice regressions. Its single dependency needs no PR limit. Renovate would duplicate an ecosystem Dependabot supports.

The toolchain file selects Python, ARM64, container, Rust, and performance-guard validation. The guard builds each revision with its own selection, so it compares compilers.

### Required source changes

Without the 1.85 minimum, Clippy 1.99 denies `chunks_exact_to_as_chunks` in `copy_words` and `Writer::write_bytes`, and `collapsible_if` in the free-list merge and the local cache's family removal. The suggested `as_chunks` and let-chain forms keep behavior. The let chains compile to identical machine code; the commit records the measured read and write effects of `as_chunks`.

## Risks / Trade-offs

- Each compiling CI job spends a few seconds downloading the minimal toolchain.
- A compiler update can change generated code; its PR runs the full native, ARM64, and guard validation before merging.
- Source builds with rustup download the selected release when it is absent.
