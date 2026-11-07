from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml

from client_query_cache._types import NonEmptyStr, NonNegativeInt, PositiveInt

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

pytestmark = pytest.mark.unit

_WORKFLOW = (
    Path(__file__).resolve().parents[1] / ".github/workflows/dependency-automerge.yml"
)
_REPOSITORY = "owner/repository"
_PR_NUMBER = 7
_PR_ID = "PR_node"
_VALIDATED_HEAD = "a" * 40
_NEWER_HEAD = "b" * 40
_BASE_HEAD = "c" * 40
_NEWER_BASE = "d" * 40

_GH_STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "${GH_LOG}"
case "$*" in
  "api --paginate --slurp repos/"*"/files?per_page=100")
    [[ -n "${GH_FILES:-}" ]] || exit 1
    printf '%s' "${GH_FILES}" ;;
  "api --paginate --slurp "*)
    [[ -n "${GH_PULLS:-}" ]] || exit 1
    printf '%s' "${GH_PULLS}" ;;
  "api graphql "*) exit "${GH_AUTO_MERGE_STATUS}" ;;
  *"/reviews "*) ;;
  "api repos/"*)
    views="$(grep -c '^api repos/[^ ]*$' "${GH_LOG}")"
    sed -n "${views}p" <<< "${GH_PR_VIEWS}" ;;
  *) exit 99 ;;
esac
"""

type StepRun = tuple[int, list[str], str]
type StepRunner = Callable[[str, int, dict[str, str]], StepRun]


def _pull_request(
    number: PositiveInt = _PR_NUMBER,
    head: NonEmptyStr = _VALIDATED_HEAD,
    *,
    base: NonEmptyStr = _BASE_HEAD,
    changed_files: NonNegativeInt = 1,
) -> NonEmptyStr:
    return json.dumps(
        {
            "number": number,
            "node_id": _PR_ID,
            "state": "open",
            "draft": False,
            "changed_files": changed_files,
            "user": {"type": "Bot", "login": "dependabot[bot]"},
            "head": {"sha": head, "repo": {"full_name": _REPOSITORY}},
            "base": {
                "ref": "main",
                "sha": base,
                "repo": {"full_name": _REPOSITORY},
            },
        }
    )


def _views(*heads: str) -> str:
    return "\n".join(_pull_request(head=head) for head in heads)


def _files(*filenames: NonEmptyStr, status: NonEmptyStr = "modified") -> NonEmptyStr:
    return json.dumps(
        [[{"filename": filename, "status": status} for filename in filenames]]
    )


@pytest.fixture(scope="module")
def run_step(tmp_path_factory: pytest.TempPathFactory) -> StepRunner:
    tmp_path = tmp_path_factory.mktemp("dependency-acceptance")
    workflow = yaml.safe_load(_WORKFLOW.read_text())
    bash = shutil.which("bash")
    assert bash is not None
    stub = tmp_path / "bin" / "gh"
    stub.parent.mkdir()
    stub.write_text(_GH_STUB)
    stub.chmod(0o755)
    log = tmp_path / "gh.log"
    output = tmp_path / "output"

    def run(job: str, step: int, environment: dict[str, str]) -> StepRun:
        log.write_text("")
        output.write_text("")
        completed = subprocess.run(  # noqa: S603 - Run a step script from the repository workflow with a resolved Bash and stubbed gh.
            (
                bash,
                "--noprofile",
                "--norc",
                "-eo",
                "pipefail",
                "-c",
                workflow["jobs"][job]["steps"][step]["run"],
            ),
            env={
                **workflow["env"],
                "PATH": f"{stub.parent}{os.pathsep}{os.environ['PATH']}",
                "GH_LOG": str(log),
                "GITHUB_OUTPUT": str(output),
                "GH_REPO": _REPOSITORY,
                "PR_POLICY": workflow["env"]["PR_POLICY"],
                "RUN_HEAD": _VALIDATED_HEAD,
                "PR_NUMBER": str(_PR_NUMBER),
                "PR_ID": _PR_ID,
                "HEAD_SHA": _VALIDATED_HEAD,
                "BASE_SHA": _BASE_HEAD,
                **environment,
            },
            capture_output=True,
            check=False,
        )
        calls = [" ".join(call.split()[:2]) for call in log.read_text().splitlines()]
        return completed.returncode, calls, output.read_text()

    return run


@pytest.mark.parametrize(
    ("pulls", "succeeds", "outputs"),
    [
        pytest.param("[[]]", True, "", id="no-eligible-pr"),
        pytest.param(
            f"[[{_pull_request()}]]",
            True,
            f"eligible=true\npr_number={_PR_NUMBER}\npr_id={_PR_ID}\n"
            f"head_sha={_VALIDATED_HEAD}\n",
            id="one-eligible-pr",
        ),
        pytest.param(
            f"[[{_pull_request()}], [{_pull_request(number=_PR_NUMBER + 1)}]]",
            False,
            "",
            id="several-eligible-prs",
        ),
        pytest.param("not JSON", False, "", id="malformed-response"),
        pytest.param("", False, "", id="api-error"),
    ],
)
def test_selection_accepts_only_a_unique_eligible_pr(
    run_step: StepRunner, pulls: str, *, succeeds: bool, outputs: str
) -> None:
    status, _, written = run_step("select", 0, {"GH_PULLS": pulls})

    assert (status == 0) is succeeds
    assert written == outputs


@pytest.mark.parametrize(
    ("files", "changed_files", "eligible", "succeeds"),
    [
        pytest.param(_files("pyproject.toml", "uv.lock"), 2, True, True, id="python"),
        pytest.param(
            _files("package.json", "package-lock.json"), 2, True, True, id="npm"
        ),
        pytest.param(
            _files("native/shared-index/Cargo.toml", "native/shared-index/Cargo.lock"),
            2,
            True,
            True,
            id="cargo",
        ),
        pytest.param(
            _files(
                "Containerfile",
                "justfile",
                ".node-version",
                ".python-version",
                "rust-toolchain.toml",
                ".pre-commit-config.yaml",
            ),
            6,
            True,
            True,
            id="tool-pins",
        ),
        pytest.param(
            _files("docker-compose.yaml", "tests/mongodb-minimum/docker-compose.yaml"),
            2,
            True,
            True,
            id="mongodb",
        ),
        pytest.param(
            _files(
                ".github/actions/setup-toolchain/action.yml",
                ".github/workflows/test.yml",
                ".github/workflows/docs.yml",
                ".github/workflows/publish.yml",
                ".github/workflows/dependency-automerge.yml",
                ".github/workflows/release-verification.yml",
                ".github/workflows/stream-cost-benchmark.yml",
            ),
            7,
            True,
            True,
            id="actions",
        ),
        pytest.param(
            _files("pyproject.toml", "src/client_query_cache/__init__.py"),
            2,
            False,
            True,
            id="python-source",
        ),
        pytest.param(
            _files("native/shared-index/src/lib.rs"), 1, False, True, id="rust-source"
        ),
        pytest.param(
            _files("tests/test_dependency_acceptance_workflow.py"),
            1,
            False,
            True,
            id="tests",
        ),
        pytest.param(_files("README.md"), 1, False, True, id="docs"),
        pytest.param(_files("renovate.json5"), 1, False, True, id="bot-policy"),
        pytest.param(
            _files(".github/workflows/new.yml"), 1, False, True, id="new-workflow"
        ),
        pytest.param(
            '[[{"filename":"pyproject.toml","status":"renamed","previous_filename":"src/library.py"}]]',
            1,
            False,
            True,
            id="rename-from-source",
        ),
        pytest.param(
            '[[{"filename":"src/library.py","status":"renamed","previous_filename":"pyproject.toml"}]]',
            1,
            False,
            True,
            id="rename-to-source",
        ),
        pytest.param(
            '[[{"filename":"package.json","status":"renamed","previous_filename":"pyproject.toml"}]]',
            1,
            True,
            True,
            id="rename-within-allowlist",
        ),
        pytest.param(
            '[[{"filename":"pyproject.toml","status":"modified"}],'
            '[{"filename":"src/library.py","status":"modified"}]]',
            2,
            False,
            True,
            id="later-page-source",
        ),
        pytest.param(
            '[[{"filename":"pyproject.toml","status":"modified"}],'
            '[{"filename":"uv.lock","status":"modified"}]]',
            2,
            True,
            True,
            id="allowed-pages",
        ),
        pytest.param(_files("uv.lock"), 2, False, False, id="incomplete"),
        pytest.param(_files("uv.lock"), 3001, False, False, id="api-limit"),
        pytest.param("[[]]", 0, False, False, id="empty"),
        pytest.param("not JSON", 1, False, False, id="malformed"),
        pytest.param(
            '[[{"status":"modified"}]]', 1, False, False, id="missing-filename"
        ),
        pytest.param(
            '[[{"filename":"uv.lock","status":"renamed","previous_filename":null}]]',
            1,
            False,
            False,
            id="malformed-rename",
        ),
        pytest.param(
            _files("pyproject.toml", status="renamed"),
            1,
            False,
            False,
            id="rename-missing-source",
        ),
        pytest.param(
            '[[{"filename":"pyproject.toml","status":"renamed","previous_filename":""}]]',
            1,
            False,
            False,
            id="rename-empty-source",
        ),
        pytest.param(
            '[[{"filename":"pyproject.toml"}]]', 1, False, False, id="missing-status"
        ),
        pytest.param(
            '[[{"filename":"pyproject.toml","status":null}]]',
            1,
            False,
            False,
            id="null-status",
        ),
        pytest.param(
            _files("pyproject.toml", status="rename"),
            1,
            False,
            False,
            id="unknown-status",
        ),
        pytest.param(_files("uv.lock", status="added"), 1, True, True, id="added-file"),
        pytest.param(
            _files("uv.lock", status="removed"), 1, True, True, id="removed-file"
        ),
        pytest.param(
            _files("uv.lock", status="copied"), 1, True, True, id="copied-file"
        ),
        pytest.param(
            _files("uv.lock", status="changed"), 1, True, True, id="changed-file"
        ),
        pytest.param(
            _files("uv.lock", status="unchanged"), 1, True, True, id="unchanged-file"
        ),
        pytest.param("", 1, False, False, id="api-error"),
    ],
)
def test_file_scope_controls_credential_eligibility(
    run_step: StepRunner,
    files: str,  # Empty simulates an API failure.
    changed_files: NonNegativeInt,
    *,
    eligible: bool,
    succeeds: bool,
) -> None:
    pr = _pull_request(changed_files=changed_files)
    status, _, written = run_step(
        "accept", 0, {"GH_FILES": files, "GH_PR_VIEWS": f"{pr}\n{pr}"}
    )

    assert (status == 0) is succeeds
    assert written == (f"eligible=true\nbase_sha={_BASE_HEAD}\n" if eligible else "")


@pytest.mark.parametrize(
    "views",
    [
        pytest.param(_views(_NEWER_HEAD), id="head-already-moved"),
        pytest.param(
            _views(_VALIDATED_HEAD, _NEWER_HEAD), id="head-moves-during-listing"
        ),
        pytest.param(
            f"{_pull_request()}\n{_pull_request(base=_NEWER_BASE)}",
            id="base-moves-during-listing",
        ),
        pytest.param(
            f"{_pull_request()}\n{_pull_request(changed_files=2)}",
            id="file-count-changes-during-listing",
        ),
    ],
)
def test_changed_diff_receives_no_credential_eligibility(
    run_step: StepRunner, views: NonEmptyStr
) -> None:
    status, _, written = run_step(
        "accept", 0, {"GH_FILES": _files("uv.lock"), "GH_PR_VIEWS": views}
    )

    assert status == 0
    assert not written


def test_credentials_and_mutations_require_verified_scope() -> None:
    workflow = yaml.safe_load(_WORKFLOW.read_text())
    privileged_steps = workflow["jobs"]["accept"]["steps"][1:]

    assert all(
        step["if"] == "steps.metadata.outputs.eligible == 'true'"
        for step in privileged_steps
    )


@pytest.mark.parametrize(("configured", "succeeds"), [("true", True), ("false", False)])
def test_missing_app_configuration_fails(
    run_step: StepRunner, configured: str, *, succeeds: bool
) -> None:
    status, calls, _ = run_step("accept", 1, {"CONFIGURED": configured})

    assert (status == 0) is succeeds
    assert calls == []


@pytest.mark.parametrize(
    ("views", "auto_merge_status", "expected_calls"),
    [
        pytest.param(
            _views(_VALIDATED_HEAD, _VALIDATED_HEAD),
            "0",
            [
                f"api repos/{_REPOSITORY}/pulls/{_PR_NUMBER}",
                "api graphql",
                f"api repos/{_REPOSITORY}/pulls/{_PR_NUMBER}",
                f"api repos/{_REPOSITORY}/pulls/{_PR_NUMBER}/reviews",
            ],
            id="accepted",
        ),
        pytest.param(
            _views(_VALIDATED_HEAD),
            "1",
            [f"api repos/{_REPOSITORY}/pulls/{_PR_NUMBER}", "api graphql"],
            id="auto-merge-rejected",
        ),
        pytest.param(
            _views(_NEWER_HEAD),
            "0",
            [f"api repos/{_REPOSITORY}/pulls/{_PR_NUMBER}"],
            id="head-moved-before-request",
        ),
        pytest.param(
            _views(_VALIDATED_HEAD, _NEWER_HEAD),
            "0",
            [
                f"api repos/{_REPOSITORY}/pulls/{_PR_NUMBER}",
                "api graphql",
                f"api repos/{_REPOSITORY}/pulls/{_PR_NUMBER}",
            ],
            id="head-moved-after-request",
        ),
        pytest.param(
            _pull_request(base=_NEWER_BASE),
            "0",
            [f"api repos/{_REPOSITORY}/pulls/{_PR_NUMBER}"],
            id="base-moved-before-request",
        ),
        pytest.param(
            f"{_pull_request()}\n{_pull_request(base=_NEWER_BASE)}",
            "0",
            [
                f"api repos/{_REPOSITORY}/pulls/{_PR_NUMBER}",
                "api graphql",
                f"api repos/{_REPOSITORY}/pulls/{_PR_NUMBER}",
            ],
            id="base-moved-after-request",
        ),
    ],
)
def test_approval_follows_only_an_accepted_auto_merge_request(
    run_step: StepRunner,
    views: str,
    auto_merge_status: str,
    expected_calls: Sequence[str],
) -> None:
    status, calls, _ = run_step(
        "accept",
        3,
        {"GH_PR_VIEWS": views, "GH_AUTO_MERGE_STATUS": auto_merge_status},
    )

    assert (status == 0) is (expected_calls[-1].endswith("/reviews"))
    assert calls == list(expected_calls)
