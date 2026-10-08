# Just 1.57.0: https://just.systems/man/en/settings.html
# The default is false. We override it because shell recipes consume original positional arguments.
set positional-arguments
# The default is running the first recipe. We override it because plain just must list commands without running setup.
set default-list

# Bash 5.3 help set; set -euo pipefail in docs-build-editions, typecheck-examples,
# verify-release, pytest, test-pymongo-min,
# enable-podman-socket, podman, test-memory, test-integration, test-e2e and
# tests_and_coverage:
# The default is inherited Bash options, normally all three off. We override it because
# failed commands, unset variables and failed pipeline stages must stop the recipe.
# npm 11 loglevel: https://docs.npmjs.com/cli/v11/using-npm/config#loglevel
# --silent in setup/format: The default is normal progress output. We override it
# because these commands should emphasize diagnostics.
dev_image := "localhost/client-query-cache-dev:0.1.0"
dev_container := "client-query-cache-dev"
# uv 0.12.9 locally / 0.12.19 in CI: https://docs.astral.sh/uv/reference/environment/#uv_locked
# The default is inherited from the caller, otherwise unset. We override it because project recipes must reject a stale lockfile.
export UV_LOCKED := "1"

setup:
    uv sync
    npm ci --silent
    prek install
    git submodule update --init

lint:
    uv run -- prek run --all-files
    # mypy 2.3.1: https://mypy.readthedocs.io/en/stable/command_line.html
    # --install-types: The default is false. We override it because quality checks also
    # install available missing stubs.
    uv run -- mypy --install-types
    just typecheck-examples
    just --fmt --check
    # OpenSpec 1.14.0 validate --help: The default is strict=false. We override it
    # because specification warnings must fail lint.
    npm exec -- openspec validate --all --strict

typecheck-examples:
    #!/usr/bin/env bash
    set -euo pipefail

    # uv 0.12.9 locally / 0.12.19 in CI: https://docs.astral.sh/uv/reference/cli/
    # env -u UV_LOCKED: The default is the exported value 1. We override it because PEP
    # 723 environments resolve dependencies without the project lockfile.
    # uv --quiet: The default is normal progress output. We override it because this
    # loop should emphasize diagnostics.
    for example in examples/*.py; do
        script_python="$(env -u UV_LOCKED uv sync --quiet --script "${example}" --output-format json | uv run -- python -c 'import json, sys; print(json.load(sys.stdin)["sync"]["environment"]["python"]["path"])')"
        # mypy 2.3.1 --python-executable: The default is mypy's interpreter. We override
        # it because each example has its own installed dependencies.
        uv run -- mypy --python-executable "${script_python}" "${example}"
    done

ci-lint:
    # zizmor 1.30.0: https://docs.zizmor.sh/usage/
    # ZIZMOR_OFFLINE: The default is false. We override it because local inspection must
    # not query GitHub APIs.
    # --fix: The default is no fixes. We override it because this recipe applies
    # available workflow corrections.
    # --persona: The default is regular. We override it because review includes pedantic
    # and lower-confidence findings.
    # -q: The default is normal logging. We override it because diagnostics should
    # remain visible without progress chatter.
    ZIZMOR_OFFLINE=true zizmor --fix=all -q --persona=auditor .github

format:
    npm run format --silent
    just --fmt

build:
    uv build

docs-serve:
    # uv 0.12.9 locally / 0.12.19 in CI --only-group docs in docs-serve/docs-build/docs-build-editions:
    # The default is the project and default groups (dev). We override it because these
    # commands need only documentation tools.
    uv run --only-group docs -- zensical serve

docs-build:
    # Zensical 0.0.68:
    # https://github.com/zensical/zensical/blob/v0.0.68/python/zensical/main.py
    # --clean: The default is false. We override it because publication checks must
    # rebuild without the prior cache.
    # --strict: The default is false. We override it because publication must fail on
    # warnings, including broken links.
    uv run --only-group docs -- zensical build --clean --strict

docs-build-editions stable_tag="":
    #!/usr/bin/env bash
    set -euo pipefail

    stable_tag="$1"
    if [[ -z "${stable_tag}" ]]; then
        # GitHub CLI: https://cli.github.com/manual/gh_api
        # --jq: The default is the complete response. We override it because the
        # assembler needs only the selected release tag.
        stable_tag="$(gh api 'repos/{owner}/{repo}/releases/latest' --jq .tag_name)"
        # Git 2.55.0: https://git-scm.com/docs/git-fetch
        # --no-tags: The default is inherited remote.origin.tagOpt, otherwise
        # auto-following reachable tags. We override it because assembly needs only
        # the selected release tag.
        git fetch --no-tags origin "refs/tags/${stable_tag}:refs/tags/${stable_tag}"
    fi
    uv run --only-group docs -- python -m scripts.build_versioned_docs "${stable_tag}"

verify-release tag='': build
    #!/usr/bin/env bash
    set -euo pipefail

    mapfile -t release_metadata <<< "$(uv run -- python -c 'import tomllib; metadata = tomllib.load(open("pyproject.toml", "rb"))["project"]; print(metadata["name"].replace("-", "_").replace(".", "_")); print(metadata["version"])')"
    package_slug="${release_metadata[0]}"
    declared_version="${release_metadata[1]}"

    if [[ -n "{{ tag }}" ]]; then
        expected_version="{{ tag }}"
        expected_version="${expected_version#v}"
        if [[ "${expected_version}" != "${declared_version}" ]]; then
            printf 'Tag %s does not match the declared package version %s.\n' "{{ tag }}" "${declared_version}" >&2
            exit 1
        fi
    fi

    sdist="dist/${package_slug}-${declared_version}.tar.gz"
    wheels=(dist/"${package_slug}"-"${declared_version}"-*.whl)
    if [[ ! -f "${sdist}" ]]; then
        printf 'Expected sdist %s was not produced by the build.\n' "${sdist}" >&2
        exit 1
    fi
    if [[ ! -f "${wheels[0]}" ]]; then
        printf 'Expected wheel for %s %s was not produced by the build.\n' "${package_slug}" "${declared_version}" >&2
        exit 1
    fi

    for artifact in "${sdist}" "${wheels[@]}"; do
        # uv --isolated --no-project: The default is the discovered project environment.
        # We override it because verification must import the installed artifact in a
        # fresh environment.
        # Python 3.14 -I: https://docs.python.org/3.14/using/cmdline.html#cmdoption-I
        # The default is normal user-site/environment/script-path loading. We override
        # it because local packages must not satisfy artifact imports.
        # The default is the exported UV_LOCKED=1. We override it because --no-project
        # ignores it and emits a warning.
        unset UV_LOCKED && uv run --isolated --no-project --python "${UV_PYTHON:-$(cat .python-version)}" --with "${artifact}" -- \
            python -I "{{ justfile_directory() }}/scripts/verify_release_artifacts.py"
    done

    printf 'Verified %s %s (%s, %s), no package published and no publishing credentials used.\n' "${package_slug}" "${declared_version}" "${sdist}" "${wheels[0]}"

pytest *args:
    #!/usr/bin/env bash
    set -euo pipefail
    [[ "${1:-}" == "--" ]] && shift

    source "{{ justfile_directory() }}/scripts/testcontainers-bridge.sh"
    env_file_args=()
    if [[ -f "{{ justfile_directory() }}/.env" ]]; then
        env_file_args=(--env-file "{{ justfile_directory() }}/.env")
    fi
    exec uv run "${env_file_args[@]}" --group docs -- pytest "$@"

test-pymongo-min:
    #!/usr/bin/env bash
    set -euo pipefail

    source "{{ justfile_directory() }}/scripts/testcontainers-bridge.sh"
    # tox 4.64.5: https://tox.wiki/en/latest/cli_interface.html
    # -r: The default reuses environments. We override it because each minimum-driver
    # run must resolve the current published dependency floor in a fresh environment.
    # -e: The default is tox.ini envlist. We override it because this command runs
    # only the minimum-driver lane.
    exec uv run -- tox run -r -e pymongo-min

build-dev-image:
    podman build --tag {{ dev_image }} .

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
        # flatpak-spawn:
        # https://docs.flatpak.org/en/latest/flatpak-command-reference.html#flatpak-spawn
        # --host here and in podman: The default is spawning through the sandbox portal.
        # We override it because Toolbx must reach the host user service and container
        # engine.
        host_bridge=(flatpak-spawn --host)
        socket_path="/run/user/${uid}/podman/podman.sock"
        container_name="Toolbx"
    else
        printf 'Run this recipe inside a Toolbx or Distrobox container.\n' >&2
        exit 1
    fi

    # systemctl: https://www.freedesktop.org/software/systemd/man/latest/systemctl.html
    # --user in enable/is-active: The default is the system manager. We override it
    # because this socket belongs to the host user's rootless service.
    # --now: The default is enabling without starting. We override it because readiness
    # checks need a live socket.
    if ! "${host_bridge[@]}" systemctl --user enable --now podman.socket; then
        printf 'Failed to enable the host podman.socket through %s. Check the host user systemd session.\n' "${container_name}" >&2
        exit 1
    fi
    # --quiet: The default is printing unit state. We override it because the exit
    # status controls the failure message.
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

# Profile synthetic cache churn without MongoDB.
test-memory:
    #!/usr/bin/env bash
    set -euo pipefail
    case "$(uname -s)" in
        Linux) ;;
        *) printf '%s\n' 'Memory tests require the locked Linux environment: https://bloomberg.github.io/memray/' >&2; exit 1 ;;
    esac
    # pytest 9.1.1 / xdist 3.8.0:
    # For -m memory: The default is not memory. We override it because this lane runs
    # allocation tests.
    # For -n 0: The default is auto. We override it because allocation measurements must
    # run without competing worker processes.
    # https://pytest-xdist.readthedocs.io/en/stable/distribution.html
    # pytest-memray 1.11.0: https://pytest-memray.readthedocs.io/en/latest/usage.html
    # --trace-python-allocators: The default is false. We override it because allocation
    # ceilings must include Python allocator activity.
    # --capture=no: The default is fd capture. We override it because retained captured
    # output would distort measurements.
    # --log-level/--log-file-level=CRITICAL: The default is pytest.ini DEBUG. We
    # override it because retained debug records would distort measurements.
    # --log-file=/dev/null: The default is pytest.ini pytest.log. We override it because
    # measurement runs must not create persistent diagnostic logs.
    # --timeout=120: The default is pytest.ini 30s. We override it because profiled
    # allocation workloads need a longer bounded runtime.
    exec uv run --group memory -- pytest tests/memory -m memory -n 0 --memray --trace-python-allocators --memray-bin-path=memory-reports --capture=no --log-level=CRITICAL --log-file=/dev/null --log-file-level=CRITICAL --timeout=120

test-integration:
    #!/usr/bin/env bash
    set -euo pipefail

    # pytest 9.1.1: https://docs.pytest.org/en/stable/reference/reference.html
    # --log-file-level=WARNING in test-integration/test-e2e/tests_and_coverage:
    # The default is pytest.ini DEBUG. We override it because uploaded CI logs need
    # warnings/failures without verbose successful-operation traces.
    pytest_log_args=()
    if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
        pytest_log_args=(--log-file-level=WARNING)
    fi
    # -m: The default is pytest.ini not memory. We override it because this lane runs
    # integration tests.
    exec just pytest -- -m 'integration and not memory' "${pytest_log_args[@]}"

test-e2e:
    #!/usr/bin/env bash
    set -euo pipefail

    pytest_log_args=()
    if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
        pytest_log_args=(--log-file-level=WARNING)
    fi
    # -m: The default is pytest.ini not memory. We override it because this lane runs
    # end-to-end tests.
    exec just pytest -- -m 'e2e and not memory' "${pytest_log_args[@]}"

examples:
    just pytest -- tests/examples

tests_and_coverage:
    #!/usr/bin/env bash
    set -euo pipefail

    coverage_workspace="$(mktemp -d /tmp/client-query-cache-coverage.XXXXXX)"
    export COVERAGE_FILE="${coverage_workspace}/.coverage"
    pytest_log_args=()
    if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
        pytest_log_args=(--log-file-level=WARNING)
    fi
    # pytest-cov 7.1.0: https://pytest-cov.readthedocs.io/en/latest/config.html
    # --cov: The default is no coverage measurement. We override it because this gate
    # enforces the 100% threshold.
    # pytest 9.1.1 -qq: The default is verbosity zero. We override it because
    # contributor output should emphasize failures.
    just pytest -- --cov -qq "${pytest_log_args[@]}"
    uv run -- python -c 'from pathlib import Path; import sys; coverage_exclusions = [(path, line_number) for path in Path("src/client_query_cache").rglob("*.py") for line_number, line in enumerate(path.read_text().splitlines(), start=1) if "pragma: no cover" in line]; sys.stderr.write("".join(f"{path}:{line_number}: prohibited pragma: no cover\n" for path, line_number in coverage_exclusions)); sys.exit(bool(coverage_exclusions))'
    uv run -- strict-no-cover
