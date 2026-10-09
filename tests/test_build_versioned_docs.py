from __future__ import annotations

import errno
import re
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, cast
from urllib.parse import urlsplit

import pytest
import tomli_w

from client_query_cache._types import PositiveInt
from scripts.build_versioned_docs import (
    Sources,
    Table,
    Text,
    assemble,
    git,
    resolve,
    run,
    select_sources,
    table,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

RELEASE_VERSION = "1.0.0"
RELEASE_TAG = f"v{RELEASE_VERSION}"
MISMATCHED_TAG = "v9.0.0"
PREVIOUS_ARTIFACT_TEXT = "Previous complete artifact\n"


def commit(repo: Path) -> Text:
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "Fixture snapshot")
    return resolve(repo, "HEAD")


@pytest.fixture
def release_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repository"
    repo.mkdir()
    run(repo, "git", "init", "-q")
    for key, value in (
        ("commit.gpgsign", "false"),
        ("user.name", "Docs fixture"),
        ("user.email", "docs@example.invalid"),
    ):
        git(repo, "config", "--local", key, value)
    (repo / "src/client_query_cache").mkdir(parents=True)
    (repo / "src/client_query_cache/__init__.py").write_text('VERSION = "released"\n')
    (repo / "examples").mkdir()
    (repo / "examples/example.py").write_text('print("released")\n')
    (repo / "examples/README.md").write_text("# Released examples\n")
    (repo / "pyproject.toml").write_text(
        f'[project]\nname = "fixture"\nversion = "{RELEASE_VERSION}"\n'
    )
    (repo / "docs/user").mkdir(parents=True)
    (repo / "docs/user/index.md").write_text("# Released guide\n")
    (repo / "docs/user/guide.md").write_text(
        '# Guide\n\n```python\n--8<-- "examples/example.py"\n```\n'
    )
    (repo / "zensical.toml").write_text("""[project]
site_name = "Fixture"
site_url = "https://example.invalid/library/"
repo_url = "https://github.com/alessio-locatelli/client-query-cache"
docs_dir = "docs/user"
[project.theme]
font = false
features = ["content.action.copy"]
[project.markdown_extensions.pymdownx.snippets]
check_paths = true
[project.plugins.llmstxt]
full_output = "llms-full.txt"
[project.plugins.llmstxt.sections]
Guides = ["*.md"]
[project.plugins.redirects.redirect_maps]
""")
    commit(repo)
    git(repo, "tag", "--no-sign", RELEASE_TAG)
    return repo


@pytest.fixture
def development_source(release_repo: Path) -> Text:
    (release_repo / "src/client_query_cache/__init__.py").write_text(
        'VERSION = "development"\n'
    )
    (release_repo / "docs/user/index.md").write_text("# Development guide\n")
    return commit(release_repo)


def test_selects_exact_release_and_independent_development(
    release_repo: Path, development_source: Text
) -> None:
    stable = resolve(release_repo, f"refs/tags/{RELEASE_TAG}")
    assert select_sources(release_repo, RELEASE_TAG, "HEAD") == Sources(
        stable=stable, development=development_source, version=RELEASE_VERSION
    )
    assert stable != development_source


@pytest.mark.parametrize(
    "tag", ["HEAD", "main", "v1.0.0rc1"], ids=["head", "branch", "prerelease"]
)
def test_requires_exact_stable_release_tag(release_repo: Path, tag: Text) -> None:
    with pytest.raises(ValueError, match=r"exact vX\.Y\.Z"):
        select_sources(release_repo, tag, "HEAD")


@pytest.fixture
def mismatched_release(release_repo: Path) -> None:
    git(release_repo, "tag", "--no-sign", MISMATCHED_TAG)


@pytest.mark.usefixtures("mismatched_release")
def test_rejects_release_version_mismatch(release_repo: Path) -> None:
    with pytest.raises(ValueError, match="tag and package version disagree"):
        select_sources(release_repo, MISMATCHED_TAG, "HEAD")


@pytest.fixture
def combined_output() -> Text | None:
    return "llms-full.txt"


@pytest.fixture
def exported_repo(release_repo: Path, combined_output: Text | None) -> Path:
    configuration_path = release_repo / "zensical.toml"
    configuration = tomllib.loads(configuration_path.read_text())
    policy = table(table(table(configuration["project"])["plugins"])["llmstxt"])
    if combined_output is None:
        del policy["full_output"]
    else:
        policy["full_output"] = combined_output
    configuration_path.write_text(tomli_w.dumps(configuration))
    commit(release_repo)
    git(release_repo, "tag", "--no-sign", "--force", RELEASE_TAG)
    return release_repo


@pytest.fixture
def artifact_exists() -> bool:
    return True


@pytest.fixture
def previous_artifact(exported_repo: Path, artifact_exists: bool) -> Path:
    output = exported_repo / "site"
    if artifact_exists:
        output.mkdir()
        (output / "previous.txt").write_text(PREVIOUS_ARTIFACT_TEXT)
    return output


@pytest.fixture
def restricted_checkout(
    exported_repo: Path,
    previous_artifact: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[Path, Path, list[Path]]]:
    temporary_storage = tmp_path_factory.mktemp("system-temp")
    monkeypatch.setenv("TMPDIR", str(temporary_storage))
    monkeypatch.setattr(tempfile, "tempdir", None)
    commands: list[Path] = []

    def record_workspace(cwd: Path, *arguments: Text) -> None:
        commands.append(cwd)
        run(cwd, *arguments)

    monkeypatch.setattr("scripts.build_versioned_docs.run", record_workspace)
    parent = exported_repo.parent
    original_mode = parent.stat().st_mode & 0o7777
    parent.chmod(original_mode & ~0o222)
    try:
        yield previous_artifact, temporary_storage, commands
    finally:
        parent.chmod(original_mode)


@pytest.mark.parametrize(
    "artifact_exists", [False, True], ids=["first-build", "replacement"]
)
@pytest.mark.usefixtures("artifact_exists")
def test_assembles_without_write_access_to_checkout_parent(
    exported_repo: Path, restricted_checkout: tuple[Path, Path, list[Path]]
) -> None:
    output, temporary_storage, commands = restricted_checkout
    assemble(
        exported_repo,
        select_sources(exported_repo, RELEASE_TAG, "HEAD"),
        output,
    )
    assert commands[0].parent == temporary_storage
    assert "Released guide" in (output / "stable/index.html").read_text()
    assert "Released guide" in (output / "dev/index.html").read_text()
    assert not (output / "previous.txt").exists()


def assert_previous_artifact(directory: Path) -> None:
    assert tuple(directory.iterdir()) == (directory / "previous.txt",)
    assert (directory / "previous.txt").read_text() == PREVIOUS_ARTIFACT_TEXT


@pytest.fixture
def failed_edition(
    exported_repo: Path, request: pytest.FixtureRequest, failed_snapshot: Text
) -> tuple[type[Exception], Text]:
    failure: tuple[type[Exception], Text]
    if request.param == "heading":
        (exported_repo / "docs/user/index.md").write_text(
            "# Invalid guide\n\n[Missing heading](#absent)\n"
        )
        failure = subprocess.CalledProcessError, "anchor does not exist"
    elif request.param == "page":
        (exported_repo / "docs/user/index.md").write_text(
            "# Invalid guide\n\n[Missing page](absent.md)\n"
        )
        failure = subprocess.CalledProcessError, "page does not exist"
    elif request.param == "snippet":
        (exported_repo / "docs/user/index.md").write_text(
            '# Invalid guide\n\n--8<-- "examples/absent.py"\n'
        )
        failure = subprocess.CalledProcessError, "Snippet at path"
    elif request.param == "outside-snippet":
        (exported_repo / "docs/user/index.md").write_text(
            '# Invalid guide\n\n--8<-- "../stable/examples/example.py"\n'
        )
        failure = subprocess.CalledProcessError, "Snippet at path"
    elif request.param == "exports":
        configuration_path = exported_repo / "zensical.toml"
        configuration = tomllib.loads(configuration_path.read_text())
        del table(table(configuration["project"])["plugins"])["llmstxt"]
        configuration_path.write_text(tomli_w.dumps(configuration))
        failure = KeyError, "llmstxt"
    else:
        git(exported_repo, "rm", "-q", "docs/user/index.md")
        failure = ValueError, "public guide layout"
    commit(exported_repo)
    if failed_snapshot == "stable":
        git(exported_repo, "tag", "--no-sign", "--force", RELEASE_TAG)
    return failure


@pytest.mark.parametrize(
    "failed_edition",
    ["heading", "page", "snippet", "outside-snippet", "layout", "exports"],
    indirect=True,
    ids=["heading", "page", "snippet", "outside-snippet", "layout", "exports"],
)
@pytest.mark.parametrize("failed_snapshot", ["stable", "dev"], ids=["stable", "dev"])
@pytest.mark.usefixtures("failed_snapshot")
def test_failed_edition_preserves_previous_artifact(
    exported_repo: Path,
    previous_artifact: Path,
    failed_edition: tuple[type[Exception], Text],
    capfd: pytest.CaptureFixture[Text],
) -> None:
    sources = select_sources(exported_repo, RELEASE_TAG, "HEAD")
    exception, diagnostic = failed_edition
    with pytest.raises(exception) as failure:
        assemble(exported_repo, sources, previous_artifact)
    if exception is subprocess.CalledProcessError:
        captured = capfd.readouterr()
        assert diagnostic in captured.out + captured.err
    else:
        assert diagnostic in str(failure.value)
    assert_previous_artifact(previous_artifact)


@pytest.fixture
def failed_swap(
    previous_artifact: Path,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Text, PositiveInt]:
    phase, error = request.param
    rename = Path.rename

    def fail_rename(source: Path, destination: Path) -> Path:
        installing = destination == previous_artifact and not source.name.startswith(
            ".docs-previous-"
        )
        restoring = destination == previous_artifact and source.name.startswith(
            ".docs-previous-"
        )
        backing_up = source == previous_artifact
        if installing:
            assert source.parent.parent == previous_artifact.parent
        if backing_up:
            assert destination.parent == previous_artifact.parent
        should_fail = {
            "backup": backing_up,
            "install": installing,
            "restore": installing or restoring,
        }[phase]
        if should_fail:
            raise OSError(
                error,
                "Forced artifact replacement failure",
                str(source),
                None,
                str(destination),
            )
        return rename(source, destination)

    monkeypatch.setattr(Path, "rename", fail_rename)
    return phase, error


@pytest.mark.parametrize(
    "failed_swap",
    [
        pytest.param((phase, error), id=f"{phase}-{errno.errorcode[error]}")
        for phase in ("backup", "install", "restore")
        for error in (errno.EXDEV, errno.EACCES)
    ],
    indirect=True,
)
def test_swap_failure_preserves_previous_artifact(
    exported_repo: Path, previous_artifact: Path, failed_swap: tuple[Text, PositiveInt]
) -> None:
    phase, error = failed_swap
    with pytest.raises(OSError, match="Forced artifact replacement failure") as failure:
        assemble(
            exported_repo,
            select_sources(exported_repo, RELEASE_TAG, "HEAD"),
            previous_artifact,
        )
    assert failure.value.errno == error
    backups = tuple(exported_repo.glob(".docs-previous-*"))
    assert_previous_artifact(backups[0] if phase == "restore" else previous_artifact)
    assert len(backups) == (1 if phase == "restore" else 0)
    assert not tuple(exported_repo.glob(".docs-artifact-*"))


@pytest.mark.parametrize("artifact_exists", [False], ids=["first-install"])
@pytest.mark.parametrize(
    "failed_swap",
    [("install", errno.EXDEV), ("install", errno.EACCES)],
    indirect=True,
    ids=["cross-device", "access-denied"],
)
@pytest.mark.usefixtures("artifact_exists")
def test_failed_first_install_leaves_no_partial_artifact(
    exported_repo: Path, previous_artifact: Path, failed_swap: tuple[Text, PositiveInt]
) -> None:
    with pytest.raises(OSError, match="Forced artifact replacement failure"):
        assemble(
            exported_repo,
            select_sources(exported_repo, RELEASE_TAG, "HEAD"),
            previous_artifact,
        )
    assert failed_swap[0] == "install"
    assert not previous_artifact.exists()
    assert not tuple(exported_repo.glob(".docs-previous-*"))
    assert not tuple(exported_repo.glob(".docs-artifact-*"))


@pytest.fixture
def development_only_edition(exported_repo: Path) -> None:
    (exported_repo / "docs/user/index.md").write_text("# DevelopmentOnlyToken\n")
    (exported_repo / "docs/user/preview.md").write_text("# UnreleasedPageToken\n")
    with (exported_repo / "zensical.toml").open("a") as configuration:
        configuration.write('[project.extra.version]\nprovider = "mike"\n')
    commit(exported_repo)


@pytest.mark.usefixtures("development_only_edition")
@pytest.mark.parametrize(
    "artifact_name", ["site", "fresh-site"], ids=["replace-artifact", "first-build"]
)
@pytest.mark.parametrize(
    "combined_output",
    ["llms-full.txt", "exports/combined.txt", None],
    ids=["combined", "nested-combined", "no-combined"],
)
def test_assembles_independent_snapshots_with_development_only_page(
    exported_repo: Path,
    previous_artifact: Path,
    artifact_name: Text,
    combined_output: Text | None,
) -> None:
    output = (
        previous_artifact if artifact_name == "site" else exported_repo / artifact_name
    )
    sources = select_sources(exported_repo, RELEASE_TAG, "HEAD")
    assemble(exported_repo, sources, output)
    assert "Released guide" in (output / "stable/index.html").read_text()
    assert "DevelopmentOnlyToken" not in (output / "stable/index.html").read_text()
    assert "DevelopmentOnlyToken" in (output / "dev/index.html").read_text()
    for edition in ("stable", "dev"):
        assert 'print("released")' in (output / edition / "guide/index.md").read_text()
    assert not (output / "stable/preview/index.html").exists()
    assert "UnreleasedPageToken" in (output / "dev/preview/index.html").read_text()
    assert "stable" in (output / "preview/index.html").read_text()
    assert "stable/guide" in (output / "guide/index.html").read_text()
    assert not (output / "previous.txt").exists()
    assert (output / "llms.txt").read_bytes() == (
        output / "stable/llms.txt"
    ).read_bytes()
    for edition in ("stable", "dev"):
        index = (output / edition / "llms.txt").read_text()
        links = re.findall(r"\]\(<(https://[^>]+)>\)", index)
        assert len(links) == (2 if edition == "stable" else 3)
        for url in links:
            assert url.startswith(f"https://example.invalid/library/{edition}/")
            destination = output / urlsplit(url).path.removeprefix("/library/")
            assert destination.is_file()
            markdown = destination.read_text()
            if edition == "stable":
                assert "DevelopmentOnlyToken" not in markdown
                assert "UnreleasedPageToken" not in markdown
        assert ("UnreleasedPageToken" in index) == (edition == "dev")
        assert "data-md-copy" in (output / edition / "index.html").read_text()
    if combined_output is None:
        for prefix in ("", "stable", "dev"):
            assert not (output / prefix / "llms-full.txt").exists()
    else:
        stable_combined = output / "stable" / combined_output
        assert (output / combined_output).read_bytes() == stable_combined.read_bytes()
        assert "DevelopmentOnlyToken" not in stable_combined.read_text()
        assert "UnreleasedPageToken" not in stable_combined.read_text()
        assert "DevelopmentOnlyToken" in (output / "dev" / combined_output).read_text()
        assert "UnreleasedPageToken" in (output / "dev" / combined_output).read_text()


@pytest.fixture
def released_export_policy(
    release_repo: Path, stable_combined: Text | None, development_combined: Text | None
) -> Path:
    configuration_path = release_repo / "zensical.toml"
    configuration = tomllib.loads(configuration_path.read_text())
    project = table(configuration["project"])
    stable_policy: Table = {
        "markdown_description": "ReleasedExportPolicyToken",
        "sections": {"Overview": ["index.md"], "Usage": ["usage/*.md"]},
    }
    if stable_combined is not None:
        stable_policy["full_output"] = stable_combined
    table(project["plugins"])["llmstxt"] = stable_policy
    configuration_path.write_text(tomli_w.dumps(configuration))
    (release_repo / "docs/user/usage").mkdir()
    stable_page = release_repo / "docs/user/usage/guide.md"
    stable_page.write_text("# ReleasedUsageToken\n")
    (release_repo / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\nversion = "1.0.1"\n'
    )
    commit(release_repo)
    git(release_repo, "tag", "--no-sign", "v1.0.1")
    (release_repo / "docs/user/usage").rename(release_repo / "docs/user/learning")
    (release_repo / "docs/user/learning/guide.md").write_text("# CurrentUsageToken\n")
    development_policy: Table = {
        "markdown_description": "CurrentExportPolicyToken",
        "sections": {"Learning": ["learning/*.md"], "Home": ["index.md"]},
    }
    if development_combined is not None:
        development_policy["full_output"] = development_combined
    table(project["plugins"])["llmstxt"] = development_policy
    configuration_path.write_text(tomli_w.dumps(configuration))
    commit(release_repo)
    return release_repo


@pytest.mark.parametrize(
    ("stable_combined", "development_combined"),
    [
        (stable, development)
        for stable in ("released/combined.txt", None)
        for development in ("llms-full.txt", None)
    ],
    ids=["both-combined", "stable-combined", "development-combined", "no-combined"],
)
def test_preserves_released_export_policy(
    released_export_policy: Path,
    stable_combined: Text | None,
    development_combined: Text | None,
) -> None:
    output = released_export_policy / "site"
    sources = select_sources(released_export_policy, "v1.0.1", "HEAD")
    assemble(released_export_policy, sources, output)
    stable_index = (output / "stable/llms.txt").read_text()
    development_index = (output / "dev/llms.txt").read_text()
    assert "ReleasedExportPolicyToken" in stable_index
    assert "CurrentExportPolicyToken" not in stable_index
    assert stable_index.index("## Overview") < stable_index.index("## Usage")
    assert "/stable/usage/guide/index.md" in stable_index
    assert "CurrentExportPolicyToken" in development_index
    assert "ReleasedExportPolicyToken" not in development_index
    assert development_index.index("## Learning") < development_index.index("## Home")
    assert "/dev/learning/guide/index.md" in development_index
    assert "ReleasedUsageToken" in (output / "stable/usage/guide/index.md").read_text()
    assert "CurrentUsageToken" in (output / "dev/learning/guide/index.md").read_text()
    assert (output / "llms.txt").read_bytes() == (
        output / "stable/llms.txt"
    ).read_bytes()
    if stable_combined is not None:
        stable_export = output / "stable" / stable_combined
        assert "ReleasedUsageToken" in stable_export.read_text()
        assert (output / stable_combined).read_bytes() == stable_export.read_bytes()
    else:
        assert not (output / "stable/released/combined.txt").exists()
        assert not (output / "released/combined.txt").exists()
    if development_combined is not None:
        assert (
            "CurrentUsageToken" in (output / "dev" / development_combined).read_text()
        )
    else:
        assert not (output / "dev/llms-full.txt").exists()
    assert not (output / "llms-full.txt").exists()


@pytest.fixture
def missing_export(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Text:
    copy = shutil.copy2
    filename = cast("Text", request.param)

    def fail_export_copy(
        source: Path | Text, destination: Path | Text, *, follow_symlinks: bool = True
    ) -> Text:
        source_path = Path(source)
        if source_path.parts[-2:] == ("stable", filename):
            source_path.rename(source_path.with_suffix(".missing"))
        return copy(source, str(destination), follow_symlinks=follow_symlinks)

    monkeypatch.setattr("scripts.build_versioned_docs.shutil.copy2", fail_export_copy)
    return filename


@pytest.mark.parametrize(
    "missing_export",
    ["llms.txt", "llms-full.txt"],
    indirect=True,
    ids=["index", "combined"],
)
def test_missing_export_preserves_previous_artifact(
    exported_repo: Path, previous_artifact: Path, missing_export: Text
) -> None:
    with pytest.raises(FileNotFoundError, match=missing_export):
        assemble(
            exported_repo,
            select_sources(exported_repo, RELEASE_TAG, "HEAD"),
            previous_artifact,
        )
    assert_previous_artifact(previous_artifact)


@pytest.fixture
def linked_artifact(exported_repo: Path) -> Path:
    target = exported_repo / "existing-artifact"
    target.mkdir()
    output = exported_repo / "site"
    output.symlink_to(target, target_is_directory=True)
    return output


def test_rejects_linked_artifact_without_changing_it(
    exported_repo: Path, linked_artifact: Path
) -> None:
    with pytest.raises(ValueError, match="symbolic link"):
        assemble(
            exported_repo,
            select_sources(exported_repo, RELEASE_TAG, "HEAD"),
            linked_artifact,
        )
    assert linked_artifact.is_symlink()
    assert tuple(linked_artifact.iterdir()) == ()
