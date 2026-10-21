# PyPI publishing setup

Before the first release, the repository owner completes two one-time steps outside this repository:

1. On [PyPI](https://pypi.org/manage/account/publishing/), register a pending trusted publisher with:
   - PyPI project name: `client-query-cache`
   - Owner: `<your_account_username>`
   - Repository name: `client-query-cache`
   - Workflow filename: `publish.yml`
   - Environment name: `pypi`
2. In the repository's GitHub Settings → Environments, create an environment named `pypi` and add at least one required reviewer. Without a required reviewer, the environment does not pause the publish workflow for approval.

The release build uses `scripts/zig-linker.sh` to omit Rust’s ignored linker
optimization argument while preserving linker diagnostics. This applies the
[cargo-zigbuild fix](https://github.com/rust-cross/cargo-zigbuild/pull/486)
that is absent from Maturin 1.15. Removal is tracked in
[issue #325](https://github.com/alessio-locatelli/client-query-cache/issues/325).
