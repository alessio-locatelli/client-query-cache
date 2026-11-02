#!/usr/bin/env bash
set -euo pipefail

# Zig rejects a separate `-u` operand: https://github.com/alessio-locatelli/client-query-cache/issues/402
arguments=()
while (($#)); do
    case "$1" in
        -u)
            arguments+=("-Wl,-u,$2")
            shift
            ;;
        *) arguments+=("$1") ;;
    esac
    shift
done
exec python "${arguments[@]}"
