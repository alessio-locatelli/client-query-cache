set positional-arguments
set default-list

dev_image := "localhost/mongodb-client-cache-dev:0.1.0"
dev_container := "mongodb-client-cache-dev"
export UV_LOCKED := "1"

setup:
    uv sync
    npm ci --silent
    prek install
    git submodule update --init

lint:
    uv run -- prek run --all-files
    uv run -- mypy --install-types
    just --fmt --check
    npm exec -- openspec validate --all --strict

ci-lint:
    ZIZMOR_OFFLINE=true zizmor --fix=all -q --persona=auditor .github

format:
    npm run format --silent
    just --fmt

pytest *args:
    #!/usr/bin/env bash
    set -euo pipefail
    [[ "${1:-}" == "--" ]] && shift

    source "{{ justfile_directory() }}/scripts/testcontainers-bridge.sh"
    exec uv run -- pytest "$@"

build-dev-image:
    podman build --tag {{ dev_image }} --file Containerfile .

create-toolbox:
    @if podman container exists {{ dev_container }}; then printf '%s already exists.\n' {{ dev_container }}; else toolbox create --image {{ dev_image }} {{ dev_container }}; fi

create-distrobox:
    @if podman container exists {{ dev_container }}; then printf '%s already exists.\n' {{ dev_container }}; else distrobox create --image {{ dev_image }} --name {{ dev_container }}; fi

enable-podman-socket:
    #!/usr/bin/env bash
    set -euo pipefail

    uid="$(id -u)"
    if command -v distrobox-host-exec >/dev/null 2>&1 && [[ ! -e /run/.toolboxenv ]]; then
        host_bridge=(distrobox-host-exec)
        socket_path="/run/host/run/user/${uid}/podman/podman.sock"
        container_name="Distrobox"
    elif [[ -e /run/.toolboxenv ]]; then
        if ! command -v flatpak-spawn >/dev/null 2>&1; then
            printf 'Toolbx requires flatpak-spawn to reach the host user service.\n' >&2
            exit 1
        fi
        host_bridge=(flatpak-spawn --host)
        socket_path="/run/user/${uid}/podman/podman.sock"
        container_name="Toolbx"
    else
        printf 'Run this recipe inside a Toolbx or Distrobox container.\n' >&2
        exit 1
    fi

    if ! "${host_bridge[@]}" systemctl --user enable --now podman.socket; then
        printf 'Failed to enable the host podman.socket through %s. Check the host user systemd session.\n' "${container_name}" >&2
        exit 1
    fi
    if ! "${host_bridge[@]}" systemctl --user is-active --quiet podman.socket; then
        printf 'The host podman.socket is not active after enablement through %s.\n' "${container_name}" >&2
        exit 1
    fi
    if ! python -c 'import socket, sys; client = socket.socket(socket.AF_UNIX); client.settimeout(3); connection_status = client.connect_ex(sys.argv[1]); client.close(); sys.exit(connection_status)' "${socket_path}"; then
        printf 'The active host podman.socket is unreachable at %s inside %s.\n' "${socket_path}" "${container_name}" >&2
        exit 1
    fi

podman *args:
    #!/usr/bin/env bash
    set -euo pipefail
    [[ "${1:-}" == "--" ]] && shift

    if command -v distrobox-host-exec >/dev/null 2>&1 && [[ ! -e /run/.toolboxenv ]]; then
        exec distrobox-host-exec podman "$@"
    elif [[ -e /run/.toolboxenv ]]; then
        if ! command -v flatpak-spawn >/dev/null 2>&1; then
            printf 'Toolbx requires flatpak-spawn for host Podman commands.\n' >&2
            exit 1
        fi
        exec flatpak-spawn --host podman "$@"
    elif command -v podman >/dev/null 2>&1; then
        exec podman "$@"
    else
        printf 'Podman is unavailable. Run this recipe on the host, in Toolbx, or in Distrobox.\n' >&2
        exit 1
    fi

test-integration:
    #!/usr/bin/env bash
    set -euo pipefail

    source "{{ justfile_directory() }}/scripts/testcontainers-bridge.sh"
    pytest_log_args=()
    if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
        pytest_log_args=(--log-file-level=WARNING)
    fi
    uv run -- pytest -m integration "${pytest_log_args[@]}"

test-e2e:
    #!/usr/bin/env bash
    set -euo pipefail

    source "{{ justfile_directory() }}/scripts/testcontainers-bridge.sh"
    pytest_log_args=()
    if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
        pytest_log_args=(--log-file-level=WARNING)
    fi
    uv run -- pytest -m e2e "${pytest_log_args[@]}"

tests_and_coverage:
    #!/usr/bin/env bash
    set -euo pipefail

    coverage_workspace="$(mktemp -d /tmp/mongodb-client-cache-coverage.XXXXXX)"
    export COVERAGE_FILE="${coverage_workspace}/.coverage"
    source "{{ justfile_directory() }}/scripts/testcontainers-bridge.sh"
    pytest_log_args=()
    if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
        pytest_log_args=(--log-file-level=WARNING)
    fi
    uv run -- coverage run -m pytest -qq "${pytest_log_args[@]}"
    uv run -- coverage report
    uv run -- python -c 'from pathlib import Path; import sys; coverage_exclusions = [(path, line_number) for path in Path("src/mongo_client_cache").rglob("*.py") for line_number, line in enumerate(path.read_text().splitlines(), start=1) if "pragma: no cover" in line]; sys.stderr.write("".join(f"{path}:{line_number}: prohibited pragma: no cover\n" for path, line_number in coverage_exclusions)); sys.exit(bool(coverage_exclusions))'
    uv run -- strict-no-cover
