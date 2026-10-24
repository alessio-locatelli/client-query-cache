#!/usr/bin/env bash
set -euo pipefail

# The default permits cargo-llvm-cov warnings. We override it because measurement
# diagnostics must fail validation (cargo-llvm-cov 0.9.1 src/main.rs).
export CARGO_LLVM_COV_DENY_WARNINGS=1

# Cargo target-dir: https://doc.rust-lang.org/cargo/reference/config.html#buildtarget-dir
# The default inherits Cargo configuration, normally target/. We override it so
# ordinary builds and Loom cannot replace artifacts while coverage is collected.
export CARGO_TARGET_DIR="${PWD}/native/shared-index/target/native-coverage"

# cargo-llvm-cov 0.9.1 external tests:
# https://github.com/taiki-e/cargo-llvm-cov#get-coverage-of-external-tests
# show-env must succeed before its output is evaluated; cleaning follows it so
# dependencies remain reusable while stale crate artifacts and profiles do not.
coverage_env="$(cargo llvm-cov show-env --sh --manifest-path native/shared-index/Cargo.toml)"
eval "${coverage_env}"
PYO3_PYTHON="$(uv python find)"
export PYO3_PYTHON
cargo llvm-cov clean --workspace --manifest-path native/shared-index/Cargo.toml
# Keep Python exports out of the native harness: PyInit__shared_index has the
# same exported name in both artifacts but different test/non-test coverage hashes.
# The instrumented wheel below measures the Python binding bodies.
cargo test --locked --quiet --manifest-path native/shared-index/Cargo.toml

mkdir -p /tmp/agents
measurement_dir="$(mktemp -d /tmp/agents/native-coverage.XXXXXX)"
printf 'Native coverage artifacts: %s\n' "${measurement_dir}"
# uv 0.13 and maturin 1.15: https://docs.astral.sh/uv/reference/cli/
# https://www.maturin.rs/distribution
# --isolated/--only-group: The defaults reuse the project environment and its
# default groups. We override them to build without replacing its editable wheel.
# --compatibility linux: The project selects manylinux_2_28. We override it because
# coverage uses the host linker rather than the portable release linker.
# --locked: The default permits Cargo.lock updates. We override it for reproducibility.
uv run --quiet --isolated --only-group build -- maturin build --compatibility linux --locked --out "${measurement_dir}/wheels"
uv venv --quiet --python "${PYO3_PYTHON}" "${measurement_dir}/venv"
# --only-group/--no-emit-project: The defaults include the editable project and
# default groups. We override them to install the instrumented wheel with locked tests.
uv export --quiet --locked --only-group test --no-emit-project --output-file "${measurement_dir}/requirements.txt"
# --link-mode copy: The default is clone on Linux. We override it because /tmp and
# uv's cache can use different filesystems, which would produce fallback warnings.
uv pip install --quiet --python "${measurement_dir}/venv/bin/python" --link-mode copy --requirement "${measurement_dir}/requirements.txt" "${measurement_dir}"/wheels/*.whl
# -n 0: pytest.ini selects auto workers. We override it to keep this bounded suite
# in one process, including its native background-thread profile counters.
"${measurement_dir}/venv/bin/python" -m pytest tests/shared_cache -m unit -n 0 -q --log-file "${measurement_dir}/pytest.log"
# --fail-under-*: The default accepts any coverage. We override it because the
# production gate requires every line and function (cargo-llvm-cov report --help).
# LLVM may warn on stderr without a failing exit status; preserve those
# diagnostics and reject the report as well as cargo-llvm-cov's own warnings.
report_status=0
cargo llvm-cov report --manifest-path native/shared-index/Cargo.toml --show-missing-lines --fail-under-lines 100 --fail-under-functions 100 2> "${measurement_dir}/report.stderr" || report_status=$?
if [[ -s "${measurement_dir}/report.stderr" ]]; then
    cat "${measurement_dir}/report.stderr" >&2
    exit 1
fi
exit "${report_status}"
