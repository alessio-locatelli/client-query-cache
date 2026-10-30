from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml

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

_GH_STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "${GH_LOG}"
case "$*" in
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


def _pull_request(number: int = _PR_NUMBER, head: str = _VALIDATED_HEAD) -> str:
    return json.dumps(
        {
            "number": number,
            "node_id": _PR_ID,
            "state": "open",
            "draft": False,
            "user": {"type": "Bot", "login": "dependabot[bot]"},
            "head": {"sha": head, "repo": {"full_name": _REPOSITORY}},
            "base": {"ref": "main", "repo": {"full_name": _REPOSITORY}},
        }
    )


def _views(*heads: str) -> str:
    return "\n".join(_pull_request(head=head) for head in heads)


@pytest.fixture
def run_step(tmp_path: Path) -> StepRunner:
    workflow = yaml.safe_load(_WORKFLOW.read_text())
    bash = shutil.which("bash")
    assert bash is not None
    stub = tmp_path / "bin" / "gh"
    stub.parent.mkdir()
    stub.write_text(_GH_STUB)
    stub.chmod(0o755)
    log = tmp_path / "gh.log"
    log.touch()
    output = tmp_path / "output"
    output.touch()

    def run(job: str, step: int, environment: dict[str, str]) -> StepRun:
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
                "PATH": f"{stub.parent}{os.pathsep}{os.environ['PATH']}",
                "GH_LOG": str(log),
                "GITHUB_OUTPUT": str(output),
                "GH_REPO": _REPOSITORY,
                "PR_POLICY": workflow["env"]["PR_POLICY"],
                "RUN_HEAD": _VALIDATED_HEAD,
                "PR_NUMBER": str(_PR_NUMBER),
                "PR_ID": _PR_ID,
                "HEAD_SHA": _VALIDATED_HEAD,
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
