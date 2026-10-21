#!/usr/bin/env bash
set -euo pipefail

# Maturin 1.15 bundles cargo-zigbuild without the upstream fix:
# https://github.com/rust-cross/cargo-zigbuild/pull/486
# Zig 0.12+ ignores this Rust linker flag. Preserve all other arguments and
# diagnostics, including optimization of the Rust code itself.
arguments=()
for argument in "$@"; do
    if [[ "${argument}" != -Wl,-O1 ]]; then
        arguments+=("${argument}")
    fi
done
exec python "${arguments[@]}"
