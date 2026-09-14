## 1. Shared bridge script

- [x] 1.1 Create `scripts/testcontainers-bridge.sh` containing the Toolbx/Distrobox/CI detection and `DOCKER_HOST`/`TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE`/`TESTCONTAINERS_RYUK_PRIVILEGED` export logic currently duplicated in `test-integration`, `test-e2e`, and `coverage`, no-op under `GITHUB_ACTIONS=true`, and preserve the existing actionable `exit 1` message otherwise. Verify by running `bash -c 'set -euo pipefail; source scripts/testcontainers-bridge.sh; env | grep -E "DOCKER_HOST|TESTCONTAINERS"'` from inside a Toolbx or Distrobox container and confirming the expected variables are exported.

## 2. justfile changes

- [x] 2.1 Refactor `test-integration`, `test-e2e`, and `coverage` to `source "{{justfile_directory()}}/scripts/testcontainers-bridge.sh"` instead of inlining the detection block, keeping each recipe's own `pytest_log_args` handling. Verify `just test-integration`, `just test-e2e`, and `just coverage` still pass from inside a Toolbx or Distrobox container with the host Podman socket enabled.
- [x] 2.2 Add a `pytest *args:` recipe that sources the shared bridge script, shifts the leading `--` only when present (`[[ "${1:-}" == "--" ]] && shift`, so a zero-argument call or a call where a contributor forgot `--` never has an argument silently discarded), and runs `exec uv run -- pytest "$@"`. Verify `just pytest -- -m unit -k <name>` and `just pytest -- tests/core/<a_test_file>.py` each select the expected tests, `just pytest -- -q -v` forwards `-q`/`-v` to pytest unmodified (flags that collide with `just`'s own short flags), a bare `just pytest` runs the full suite without erroring, and `just pytest tests/core/<a_test_file>.py` (`--` omitted) still selects the expected test instead of silently running the full suite.
- [x] 2.3 Remove the `test` recipe.
- [x] 2.4 Fix `podman *args:`'s unconditional `shift` (identical defect: forgetting `--` silently drops the first argument) to the same `[[ "${1:-}" == "--" ]] && shift` guard. Verify `just podman ps` (no `--`) and `just podman -- ps` (with `--`) produce identical, correct output against the host Podman.

## 3. Documentation

- [x] 3.1 Update `CONTRIBUTING.md`: replace the `just test` reference with the direct `uv run -- pytest -m unit` command, and replace "Use pytest directly for its selection options" with `just pytest -- <args>` usage, including the `--` requirement (mirroring the existing `just podman -- <arguments>` example).

## 4. Code Quality

- [x] 4.1 Scan the entire file for edited or added tests (including pre-existing tests within the file) and ensure that the "Writing Tests" guidelines from AGENTS.md are applied, including test parametrization. Note: not applicable to the changes - this change touches only `justfile`, a new shell script, and documentation; no test files are edited or added.
