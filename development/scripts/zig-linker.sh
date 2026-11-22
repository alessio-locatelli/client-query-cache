#!/usr/bin/env bash
# set -euo pipefail: The default is inherited from an exported SHELLOPTS, otherwise
# off (verified against the SHELLOPTS entry in the Bash 5.3 manual). We override it
# because failed commands, unset variables and failed pipelines must stop linking.
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
