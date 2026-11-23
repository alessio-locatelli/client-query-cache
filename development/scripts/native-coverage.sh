#!/usr/bin/env bash
# set -euo pipefail: The default is inherited from an exported SHELLOPTS, otherwise
# off (verified against the SHELLOPTS entry in the Bash 5.3 manual). We override it
# because failed commands, unset variables and failed pipelines must stop coverage
# validation.
set -euo pipefail

# CARGO_LLVM_COV_DENY_WARNINGS: The default is inherited from the caller, otherwise
# unset, which lets warnings succeed
# (https://github.com/taiki-e/cargo-llvm-cov/blob/v0.9.1/src/main.rs#L54). We override
# it because measurement diagnostics must fail validation.
export CARGO_LLVM_COV_DENY_WARNINGS=1

# CARGO_TARGET_DIR: The default is inherited from the caller, otherwise Cargo's
# build.target-dir configuration, otherwise target/ in the workspace root
# (https://doc.rust-lang.org/1.100.0/cargo/reference/config.html#buildtarget-dir). We
# override it because ordinary builds and Loom must not replace artifacts while
# coverage is collected.
export CARGO_TARGET_DIR="${PWD}/src/shared-index/target/native-coverage"

# External-test workflow:
# https://github.com/taiki-e/cargo-llvm-cov/blob/v0.9.1/README.md#get-coverage-of-external-tests
# show-env must succeed before its output is evaluated; cleaning follows it so
# dependencies remain reusable while stale crate artifacts and profiles do not.
coverage_env="$(cargo llvm-cov show-env --sh --manifest-path src/shared-index/Cargo.toml)"
eval "${coverage_env}"
PYO3_PYTHON="$(uv python find)"
export PYO3_PYTHON
cargo llvm-cov clean --workspace --manifest-path src/shared-index/Cargo.toml
# Keep Python exports out of the native harness: PyInit__shared_index has the
# same exported name in both artifacts but different test/non-test coverage hashes.
# The instrumented wheel below measures the Python binding bodies.
# --locked in cargo test, maturin build, and uv export: The default permits lockfile
# updates, unless UV_LOCKED is inherited for uv. We override it because measurement
# must reject stale locked metadata.
cargo test --locked --quiet --manifest-path src/shared-index/Cargo.toml

mkdir -p /tmp/agents
measurement_dir="$(mktemp -d /tmp/agents/native-coverage.XXXXXX)"
printf 'Native coverage artifacts: %s\n' "${measurement_dir}"
# --isolated: The default is inherited from UV_ISOLATED, otherwise reusing and updating
# the project environment (https://github.com/astral-sh/uv/blob/0.13.6/crates/uv-cli/src/lib.rs#L3354-L3365).
# We override it because coverage must leave the ordinary installation unchanged.
# --only-group build: The default installs the project and its default groups
# (https://github.com/astral-sh/uv/blob/0.13.6/crates/uv-cli/src/lib.rs#L6808-L6814).
# We override it because building the wheel needs only maturin.
# --compatibility linux: The default is inherited from [tool.maturin] compatibility in
# pyproject.toml
# (https://github.com/PyO3/maturin/blob/v1.16.0/guide/src/distribution.md). We
# override it because coverage uses the host linker rather than the portable release
# linker.
uv run --quiet --isolated --only-group build -- maturin build --compatibility linux --locked --out "${measurement_dir}/wheels"
uv venv --quiet --python "${PYO3_PYTHON}" "${measurement_dir}/venv"
# --only-group test: The default exports the project and its default groups, as for
# uv run above. We override it because the instrumented wheel replaces the project and
# only test dependencies are needed.
uv export --quiet --locked --only-group test --output-file "${measurement_dir}/requirements.txt"
# --link-mode copy: The default is inherited from UV_LINK_MODE, otherwise clone on
# Linux (https://github.com/astral-sh/uv/blob/0.13.6/crates/uv-cli/src/lib.rs#L7355-L7370).
# We override it because /tmp and uv's cache can use different filesystems, which
# would produce fallback warnings.
uv pip install --quiet --python "${measurement_dir}/venv/bin/python" --link-mode copy --requirement "${measurement_dir}/requirements.txt" "${measurement_dir}"/wheels/*.whl
# -n 0: The default is inherited from the shared pytest configuration addopts, -n auto. We override it
# because this bounded suite and its native background-thread profile counters must
# stay in one process.
# TMPDIR: The default is inherited from the caller, otherwise unset, so tempfile falls
# back to a platform directory such as /tmp
# (https://docs.python.org/3.15/library/tempfile.html#tempfile.gettempdir). We
# override it because test artifacts must remain under this measurement's /tmp/agents
# directory.
TMPDIR="${measurement_dir}" "${measurement_dir}/venv/bin/python" -m pytest tests/shared_cache -m unit -n 0 -q --log-file "${measurement_dir}/pytest.log"
# --fail-under-*: The default accepts any coverage. We override it because the
# production gate requires every line and function (cargo-llvm-cov report --help).
# LLVM may warn on stderr without a failing exit status; preserve those
# diagnostics and reject the report as well as cargo-llvm-cov's own warnings.
report_status=0
cargo llvm-cov report --manifest-path src/shared-index/Cargo.toml --show-missing-lines --fail-under-lines 100 --fail-under-functions 100 2> "${measurement_dir}/report.stderr" || report_status=$?
if [[ -s "${measurement_dir}/report.stderr" ]]; then
    cat "${measurement_dir}/report.stderr" >&2
    exit 1
fi
exit "${report_status}"
