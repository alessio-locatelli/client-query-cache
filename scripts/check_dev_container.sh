#!/usr/bin/env bash
# Build and check the contributor image with docker, podman, or a host bridge.
set -euo pipefail

image=localhost/client-query-cache-pin-check
python_version="$(cat .python-version)"
prek_version="$(awk -F= '/^ARG PREK_TOOL_VERSION=/ {print $2}' Containerfile)"
taplo_version="$(awk -F= '/^ARG TAPLO_TOOL_VERSION=/ {print $2}' Containerfile)"
zizmor_version="$(awk -F= '/^ARG ZIZMOR_TOOL_VERSION=/ {print $2}' Containerfile)"

# Only declared build inputs enter the context, including through a host bridge.
tar -cf - Containerfile .python-version | "$@" build --quiet --tag "${image}" --file Containerfile -
# shellcheck disable=SC2016 # Expected versions are expanded inside the container.
"$@" run --rm \
    --env "EXPECTED_PYTHON=${python_version}" \
    --env "EXPECTED_PREK=${prek_version}" \
    --env "EXPECTED_TAPLO=${taplo_version}" \
    --env "EXPECTED_ZIZMOR=${zizmor_version}" \
    "${image}" bash -ec '
        rpm -q bash just nodejs24 nodejs24-npm uv
        bash --version
        just --version
        node --version | grep -E "^v24\."
        npm --version
        uv --version
        test "$(python3.14 --version)" = "Python ${EXPECTED_PYTHON}"
        test "$(prek --version)" = "prek ${EXPECTED_PREK}"
        test "$(taplo --version)" = "taplo ${EXPECTED_TAPLO}"
        test "$(zizmor --version)" = "zizmor ${EXPECTED_ZIZMOR}"
    '
