#!/usr/bin/env bash
# Build and check the contributor image with docker, podman, or a host bridge.
# Bash 5.3 help set: The default is inherited Bash options, normally all three off. We
# override it because failed commands, unset variables and failed pipelines must stop
# validation.
set -euo pipefail

image=localhost/client-query-cache-pin-check
python_version="$(cat .python-version)"
node_version="$(cat .node-version)"
node_major="${node_version%%.*}"
prek_version="$(awk -F= '/^ARG PREK_TOOL_VERSION=/ {print $2}' Containerfile)"
taplo_version="$(awk -F= '/^ARG TAPLO_TOOL_VERSION=/ {print $2}' Containerfile)"
zizmor_version="$(awk -F= '/^ARG ZIZMOR_TOOL_VERSION=/ {print $2}' Containerfile)"

# Only declared build inputs enter the context, including through a host bridge.
# Docker/Podman build --quiet: The default is normal progress output. We override it
# because contributor checks should emphasize diagnostics.
# --file Containerfile is required across engines: Docker defaults to Dockerfile, while
# Podman also recognizes Containerfile.
tar -cf - Containerfile .python-version .node-version | "$@" build --quiet --tag "${image}" --file Containerfile -
# shellcheck disable=SC2016 # Expected versions are expanded inside the container.
# Docker run: https://docs.docker.com/engine/containers/run/
# --rm: The default is retaining stopped containers. We override it because completed
# disposable checks must not leave stopped containers.
# bash -e below: The default is off in this fresh process. We override it because failed
# version checks must fail container validation.
"$@" run --rm \
    --env "EXPECTED_PYTHON=${python_version}" \
    --env "EXPECTED_NODE_MAJOR=${node_major}" \
    --env "EXPECTED_PREK=${prek_version}" \
    --env "EXPECTED_TAPLO=${taplo_version}" \
    --env "EXPECTED_ZIZMOR=${zizmor_version}" \
    "${image}" bash -ec '
        rpm -q bash just "nodejs${EXPECTED_NODE_MAJOR}" "nodejs${EXPECTED_NODE_MAJOR}-npm" uv
        bash --version
        just --version
        node --version | grep -E "^v${EXPECTED_NODE_MAJOR}\."
        npm --version
        uv --version
        python_executable="$(uv python find "${EXPECTED_PYTHON}")"
        test "$("${python_executable}" --version)" = "Python ${EXPECTED_PYTHON}"
        test "$(prek --version)" = "prek ${EXPECTED_PREK}"
        test "$(taplo --version)" = "taplo ${EXPECTED_TAPLO}"
        test "$(zizmor --version)" = "zizmor ${EXPECTED_ZIZMOR}"
    '
