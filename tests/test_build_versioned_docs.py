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


def commit(repo: Path) -> Text:
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "Fixture snapshot")
    return resolve(repo, "HEAD")


def record_backport(
    repo: Path,
    source: Text,
    tag: Text = "v0.2.0",
    fetch_ref: Text = "refs/pull/143/head",
) -> None:
    git(repo, "update-ref", "refs/pull/143/head", "HEAD")
    (repo / "stable-docs.toml").write_text(
        f'[backports."{tag}"]\nsource = "{source}"\nfetch_ref = "{fetch_ref}"\n'
    )


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
        '[project]\nname = "fixture"\nversion = "0.2.0"\n'
    )
    (repo / "docs/user").mkdir(parents=True)
    (repo / "docs/user/index.md").write_text("# Released guide\n")
    (repo / "docs/user/guide.md").write_text("# Guide\n")
    (repo / "zensical.toml").write_text("""[project]
site_name = "Fixture"
site_url = "https://example.invalid/library/"
repo_url = "https://github.com/alessio-locatelli/client-query-cache"
docs_dir = "docs/user"
site_dir = "site"
strict = true
[project.theme]
font = false
[project.validation]
invalid_links = true
invalid_link_anchors = true
[project.markdown_extensions.pymdownx.snippets]
base_path = ["."]
check_paths = true
restrict_base_path = true
[project.plugins.redirects.redirect_maps]
""")
    commit(repo)
    git(repo, "tag", "--no-sign", "v0.2.0")
    (repo / "docs/user/index.md").write_text("# Corrected guide\n")
    record_backport(repo, commit(repo))
    return repo


@pytest.fixture
def selection_sources(release_repo: Path, request: pytest.FixtureRequest) -> Sources:
    correction = resolve(release_repo, "HEAD")
    if request.param == "release":
        (release_repo / "stable-docs.toml").write_text("[backports]\n")
    elif request.param == "different-tag":
        record_backport(release_repo, correction, "v0.1.0")
    (release_repo / "src/client_query_cache/__init__.py").write_text(
        'VERSION = "development"\n'
    )
    return Sources(
        release=resolve(release_repo, "refs/tags/v0.2.0"),
        stable=correction
        if request.param == "backport"
        else resolve(release_repo, "refs/tags/v0.2.0"),
        development=commit(release_repo),
        version="0.2.0",
    )


@pytest.mark.parametrize(
    "selection_sources", ["release", "backport", "different-tag"], indirect=True
)
def test_selects_exact_release_and_independent_development(
    release_repo: Path, selection_sources: Sources
) -> None:
    assert select_sources(release_repo, "v0.2.0", "HEAD") == selection_sources


@pytest.fixture
def incompatible_backport(release_repo: Path, request: pytest.FixtureRequest) -> None:
    path, replacement = request.param
    (release_repo / path).write_text(replacement)
    record_backport(release_repo, commit(release_repo))


@pytest.mark.parametrize(
    "incompatible_backport",
    [
        pytest.param(
            ("src/client_query_cache/__init__.py", 'VERSION = "unreleased"\n'),
            id="runtime",
        ),
        pytest.param(
            ("examples/example.py", 'print("unreleased")\n'), id="executable-example"
        ),
        pytest.param(
            ("pyproject.toml", '[project]\nname = "changed"\nversion = "0.2.0"\n'),
            id="project-metadata",
        ),
    ],
    indirect=True,
)
@pytest.mark.usefixtures("incompatible_backport")
def test_rejects_incompatible_backport(release_repo: Path) -> None:
    with pytest.raises(ValueError, match="differs from the released"):
        select_sources(release_repo, "v0.2.0", "HEAD")


@pytest.fixture
def mutable_backport(release_repo: Path, request: pytest.FixtureRequest) -> None:
    record_backport(release_repo, request.param)


@pytest.mark.parametrize("mutable_backport", ["HEAD", "main", "v0.2.0"], indirect=True)
@pytest.mark.usefixtures("mutable_backport")
def test_rejects_mutable_backport_provenance(release_repo: Path) -> None:
    with pytest.raises(ValueError, match="immutable commit SHA"):
        select_sources(release_repo, "v0.2.0", "HEAD")


@pytest.fixture
def correction_ref(release_repo: Path, request: pytest.FixtureRequest) -> Text:
    correction = resolve(release_repo, "HEAD")
    if request.param == "tag":
        git(release_repo, "tag", "--no-sign", "docs-v0.2.0")
        record_backport(release_repo, correction, fetch_ref="refs/tags/docs-v0.2.0")
    elif request.param == "unreachable":
        git(release_repo, "update-ref", "refs/pull/143/head", "refs/tags/v0.2.0")
    else:
        record_backport(release_repo, correction, fetch_ref="refs/heads/main")
    return correction


@pytest.mark.parametrize("correction_ref", ["tag"], indirect=True)
def test_accepts_tag_transport(release_repo: Path, correction_ref: Text) -> None:
    assert select_sources(release_repo, "v0.2.0", "HEAD")["stable"] == correction_ref


@pytest.mark.parametrize("correction_ref", ["unreachable", "branch"], indirect=True)
@pytest.mark.usefixtures("correction_ref")
def test_rejects_unretained_correction(release_repo: Path) -> None:
    with pytest.raises(ValueError, match="fetch ref"):
        select_sources(release_repo, "v0.2.0", "HEAD")


@pytest.fixture
def merged_checkout(release_repo: Path, tmp_path: Path) -> Path:
    correction = resolve(release_repo, "HEAD")
    git(release_repo, "branch", "-m", "correction")
    git(release_repo, "checkout", "-q", "-b", "main", "v0.2.0")
    (release_repo / "docs/user/index.md").write_text("# Corrected guide\n")
    record_backport(release_repo, correction)
    commit(release_repo)
    git(release_repo, "update-ref", "refs/pull/143/head", correction)
    git(release_repo, "branch", "-D", "correction")
    remote = tmp_path / "remote.git"
    run(tmp_path, "git", "clone", "-q", "--bare", str(release_repo), str(remote))
    git(
        remote,
        "fetch",
        "-q",
        str(release_repo),
        "refs/pull/143/head:refs/pull/143/head",
    )
    checkout = tmp_path / "fresh-checkout"
    run(tmp_path, "git", "clone", "-q", f"file://{remote}", str(checkout))
    return checkout


def test_retained_pr_ref_recovers_correction_after_rebase_merge(
    merged_checkout: Path,
) -> None:
    with pytest.raises(subprocess.CalledProcessError):
        resolve(merged_checkout, "refs/pull/143/head")
    git(
        merged_checkout,
        "fetch",
        "-q",
        "--no-tags",
        "origin",
        "refs/pull/143/head:refs/pull/143/head",
    )
    sources = select_sources(merged_checkout, "v0.2.0", "HEAD")
    assert sources["stable"] != sources["development"]
    assert resolve(merged_checkout, "refs/pull/143/head") == sources["stable"]
    assert (
        git(merged_checkout, "show", f"{sources['stable']}:docs/user/index.md")
        == b"# Corrected guide\n"
    )


@pytest.mark.parametrize("tag", ["HEAD", "main", "v0.2.0rc1"])
def test_requires_exact_stable_release_tag(release_repo: Path, tag: Text) -> None:
    with pytest.raises(ValueError, match=r"exact vX\.Y\.Z"):
        select_sources(release_repo, tag, "HEAD")


@pytest.fixture
def mismatched_release(release_repo: Path) -> None:
    git(release_repo, "tag", "--no-sign", "v0.3.0")


@pytest.mark.usefixtures("mismatched_release")
def test_rejects_release_version_mismatch(release_repo: Path) -> None:
    with pytest.raises(ValueError, match="tag and package version disagree"):
        select_sources(release_repo, "v0.3.0", "HEAD")


@pytest.fixture
def combined_output() -> Text | None:
    return "llms-full.txt"


@pytest.fixture
def exported_repo(release_repo: Path, combined_output: Text | None) -> Path:
    with (release_repo / "zensical.toml").open("a") as configuration:
        configuration.write("[project.plugins.llmstxt]\n")
        if combined_output is not None:
            configuration.write(f'full_output = "{combined_output}"\n')
        configuration.write('[project.plugins.llmstxt.sections]\nGuides = ["*.md"]\n')
    commit(release_repo)
    return release_repo


@pytest.fixture
def artifact_exists() -> bool:
    return True


@pytest.fixture
def previous_artifact(exported_repo: Path, artifact_exists: bool) -> Path:
    output = exported_repo / "site"
    if artifact_exists:
        output.mkdir()
        (output / "previous.txt").write_text("Previous complete artifact\n")
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
    commands: list[Path] = []  # No commands run before assembly starts.

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
        select_sources(exported_repo, "v0.2.0", "HEAD"),
        output,
    )
    assert commands[0].parent == temporary_storage
    assert "Corrected guide" in (output / "stable/index.html").read_text()
    assert "Corrected guide" in (output / "dev/index.html").read_text()
    assert not (output / "previous.txt").exists()


@pytest.fixture
def failed_edition(
    exported_repo: Path, request: pytest.FixtureRequest
) -> type[Exception]:
    if request.param == "heading":
        (exported_repo / "docs/user/index.md").write_text(
            "# Invalid guide\n\n[Missing heading](#absent)\n"
        )
    else:
        git(exported_repo, "rm", "-q", "docs/user/index.md")
    commit(exported_repo)
    return subprocess.CalledProcessError if request.param == "heading" else ValueError


@pytest.mark.parametrize("failed_edition", ["heading", "layout"], indirect=True)
def test_failed_edition_preserves_previous_artifact(
    exported_repo: Path, previous_artifact: Path, failed_edition: type[Exception]
) -> None:
    sources = select_sources(exported_repo, "v0.2.0", "HEAD")
    with pytest.raises(failed_edition):
        assemble(exported_repo, sources, previous_artifact)
    assert tuple(previous_artifact.iterdir()) == (previous_artifact / "previous.txt",)
    assert (
        previous_artifact / "previous.txt"
    ).read_text() == "Previous complete artifact\n"


@pytest.fixture
def failed_swap(
    previous_artifact: Path,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Text, int]:  # An OS error code is positive.
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
        (phase, error)
        for phase in ("backup", "install", "restore")
        for error in (errno.EXDEV, errno.EACCES)
    ],
    indirect=True,
)
def test_swap_failure_preserves_previous_artifact(
    exported_repo: Path, previous_artifact: Path, failed_swap: tuple[Text, int]
) -> None:
    phase, error = failed_swap
    with pytest.raises(OSError, match="Forced artifact replacement failure") as failure:
        assemble(
            exported_repo,
            select_sources(exported_repo, "v0.2.0", "HEAD"),
            previous_artifact,
        )
    assert failure.value.errno == error
    backups = tuple(exported_repo.glob(".docs-previous-*"))
    preserved = backups[0] if phase == "restore" else previous_artifact
    assert (preserved / "previous.txt").read_text() == "Previous complete artifact\n"
    assert tuple(preserved.iterdir()) == (preserved / "previous.txt",)
    assert len(backups) == (1 if phase == "restore" else 0)
    assert not tuple(exported_repo.glob(".docs-artifact-*"))


@pytest.mark.parametrize("artifact_exists", [False])
@pytest.mark.parametrize(
    "failed_swap", [("install", errno.EXDEV), ("install", errno.EACCES)], indirect=True
)
@pytest.mark.usefixtures("artifact_exists")
def test_failed_first_install_leaves_no_partial_artifact(
    exported_repo: Path, previous_artifact: Path, failed_swap: tuple[Text, int]
) -> None:
    with pytest.raises(OSError, match="Forced artifact replacement failure"):
        assemble(
            exported_repo,
            select_sources(exported_repo, "v0.2.0", "HEAD"),
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
    sources = select_sources(exported_repo, "v0.2.0", "HEAD")
    assemble(exported_repo, sources, output)
    assert "Corrected guide" in (output / "stable/index.html").read_text()
    assert "DevelopmentOnlyToken" not in (output / "stable/index.html").read_text()
    assert "DevelopmentOnlyToken" in (output / "dev/index.html").read_text()
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
        '[project]\nname = "fixture"\nversion = "0.2.1"\n'
    )
    commit(release_repo)
    git(release_repo, "tag", "--no-sign", "v0.2.1")
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
    sources = select_sources(released_export_policy, "v0.2.1", "HEAD")
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


@pytest.mark.parametrize("missing_export", ["llms.txt", "llms-full.txt"], indirect=True)
def test_missing_export_preserves_previous_artifact(
    exported_repo: Path, previous_artifact: Path, missing_export: Text
) -> None:
    with pytest.raises(FileNotFoundError, match=missing_export):
        assemble(
            exported_repo,
            select_sources(exported_repo, "v0.2.0", "HEAD"),
            previous_artifact,
        )
    assert tuple(previous_artifact.iterdir()) == (previous_artifact / "previous.txt",)
    assert (
        previous_artifact / "previous.txt"
    ).read_text() == "Previous complete artifact\n"


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
            select_sources(exported_repo, "v0.2.0", "HEAD"),
            linked_artifact,
        )
    assert linked_artifact.is_symlink()
    assert tuple(linked_artifact.iterdir()) == ()
