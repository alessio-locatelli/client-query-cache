from __future__ import annotations

import errno
import os
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from scripts.build_versioned_docs import (
    Sources,
    Text,
    assemble,
    git,
    resolve,
    run,
    select_sources,
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
def artifact_exists() -> bool:
    return True


@pytest.fixture
def previous_artifact(release_repo: Path, artifact_exists: bool) -> Path:
    output = release_repo / "site"
    if artifact_exists:
        output.mkdir()
        (output / "previous.txt").write_text("Previous complete artifact\n")
    return output


@pytest.fixture
def restricted_checkout(
    release_repo: Path,
    previous_artifact: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Path]:
    temporary_storage = tmp_path_factory.mktemp("system-temp")
    monkeypatch.setenv("TMPDIR", str(temporary_storage))
    monkeypatch.setattr(tempfile, "tempdir", None)
    parent = release_repo.parent
    original_mode = parent.stat().st_mode & 0o7777
    parent.chmod(original_mode & ~0o222)
    try:
        if os.access(parent, os.W_OK):
            pytest.skip("This environment bypasses directory write permissions")
        yield previous_artifact
    finally:
        parent.chmod(original_mode)


@pytest.mark.parametrize(
    "artifact_exists", [False, True], ids=["first-build", "replacement"]
)
@pytest.mark.usefixtures("artifact_exists")
def test_assembles_without_write_access_to_checkout_parent(
    release_repo: Path, restricted_checkout: Path
) -> None:
    assemble(
        release_repo,
        select_sources(release_repo, "v0.2.0", "HEAD"),
        restricted_checkout,
    )
    assert "Corrected guide" in (restricted_checkout / "stable/index.html").read_text()
    assert "Corrected guide" in (restricted_checkout / "dev/index.html").read_text()
    assert not (restricted_checkout / "previous.txt").exists()


@pytest.fixture
def failed_edition(
    release_repo: Path, request: pytest.FixtureRequest
) -> type[Exception]:
    if request.param == "heading":
        (release_repo / "docs/user/index.md").write_text(
            "# Invalid guide\n\n[Missing heading](#absent)\n"
        )
    else:
        git(release_repo, "rm", "-q", "docs/user/index.md")
    commit(release_repo)
    return subprocess.CalledProcessError if request.param == "heading" else ValueError


@pytest.mark.parametrize("failed_edition", ["heading", "layout"], indirect=True)
def test_failed_edition_preserves_previous_artifact(
    release_repo: Path, previous_artifact: Path, failed_edition: type[Exception]
) -> None:
    sources = select_sources(release_repo, "v0.2.0", "HEAD")
    with pytest.raises(failed_edition):
        assemble(release_repo, sources, previous_artifact)
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
    release_repo: Path, previous_artifact: Path, failed_swap: tuple[Text, int]
) -> None:
    phase, error = failed_swap
    with pytest.raises(OSError, match="Forced artifact replacement failure") as failure:
        assemble(
            release_repo,
            select_sources(release_repo, "v0.2.0", "HEAD"),
            previous_artifact,
        )
    assert failure.value.errno == error
    backups = tuple(release_repo.glob(".docs-previous-*"))
    preserved = backups[0] if phase == "restore" else previous_artifact
    assert (preserved / "previous.txt").read_text() == "Previous complete artifact\n"
    assert tuple(preserved.iterdir()) == (preserved / "previous.txt",)
    assert len(backups) == (1 if phase == "restore" else 0)
    assert not tuple(release_repo.glob(".docs-artifact-*"))


@pytest.mark.parametrize("artifact_exists", [False])
@pytest.mark.parametrize(
    "failed_swap", [("install", errno.EXDEV), ("install", errno.EACCES)], indirect=True
)
@pytest.mark.usefixtures("artifact_exists")
def test_failed_first_install_leaves_no_partial_artifact(
    release_repo: Path, previous_artifact: Path, failed_swap: tuple[Text, int]
) -> None:
    with pytest.raises(OSError, match="Forced artifact replacement failure"):
        assemble(
            release_repo,
            select_sources(release_repo, "v0.2.0", "HEAD"),
            previous_artifact,
        )
    assert failed_swap[0] == "install"
    assert not previous_artifact.exists()
    assert not tuple(release_repo.glob(".docs-previous-*"))
    assert not tuple(release_repo.glob(".docs-artifact-*"))


@pytest.fixture
def development_only_edition(release_repo: Path) -> None:
    (release_repo / "docs/user/index.md").write_text("# DevelopmentOnlyToken\n")
    (release_repo / "docs/user/preview.md").write_text("# UnreleasedPageToken\n")
    with (release_repo / "zensical.toml").open("a") as configuration:
        configuration.write('[project.extra.version]\nprovider = "mike"\n')
    commit(release_repo)


@pytest.mark.usefixtures("development_only_edition")
@pytest.mark.parametrize(
    "artifact_name", ["site", "fresh-site"], ids=["replace-artifact", "first-build"]
)
def test_assembles_independent_snapshots_with_development_only_page(
    release_repo: Path, previous_artifact: Path, artifact_name: Text
) -> None:
    output = (
        previous_artifact if artifact_name == "site" else release_repo / artifact_name
    )
    sources = select_sources(release_repo, "v0.2.0", "HEAD")
    assemble(release_repo, sources, output)
    assert "Corrected guide" in (output / "stable/index.html").read_text()
    assert "DevelopmentOnlyToken" not in (output / "stable/index.html").read_text()
    assert "DevelopmentOnlyToken" in (output / "dev/index.html").read_text()
    assert not (output / "stable/preview/index.html").exists()
    assert "UnreleasedPageToken" in (output / "dev/preview/index.html").read_text()
    assert "stable" in (output / "preview/index.html").read_text()
    assert "stable/guide" in (output / "guide/index.html").read_text()
    assert not (output / "previous.txt").exists()


@pytest.fixture
def linked_artifact(release_repo: Path) -> Path:
    target = release_repo / "existing-artifact"
    target.mkdir()
    output = release_repo / "site"
    output.symlink_to(target, target_is_directory=True)
    return output


def test_rejects_linked_artifact_without_changing_it(
    release_repo: Path, linked_artifact: Path
) -> None:
    with pytest.raises(ValueError, match="symbolic link"):
        assemble(
            release_repo,
            select_sources(release_repo, "v0.2.0", "HEAD"),
            linked_artifact,
        )
    assert linked_artifact.is_symlink()
    assert tuple(linked_artifact.iterdir()) == ()
