"""Assemble release and development documentation using mike and Zensical."""

from __future__ import annotations

import argparse
import io
import re
import shutil
import subprocess
import tarfile
import tomllib
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TypedDict, cast
from uuid import uuid4

import tomli_w

type Text = str  # Git arguments and TOML strings can be empty.
type Table = dict[Text, object]  # A TOML table can be empty.


def table(value: object) -> Table:
    return cast("Table", value)


class Sources(TypedDict):
    release: Text
    stable: Text
    development: Text
    version: Text


def git(repo: Path, *arguments: Text) -> bytes:
    return subprocess.run(  # noqa: S603 - Argument vectors never use a shell.
        ("git", "-C", str(repo), *arguments),  # noqa: S607 - Git is supplied by the toolchain.
        check=True,
        stdout=subprocess.PIPE,
    ).stdout


def resolve(repo: Path, revision: Text) -> Text:
    return (
        git(repo, "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}")
        .decode()
        .strip()
    )


def project_metadata(repo: Path, revision: Text) -> Table:
    return table(
        tomllib.loads(git(repo, "show", f"{revision}:pyproject.toml").decode())[
            "project"
        ]
    )


def executable_examples(repo: Path, revision: Text) -> bytes:
    entries = git(repo, "ls-tree", "-r", revision, "examples").splitlines()
    return b"\n".join(entry for entry in entries if entry.endswith(b".py"))


def select_sources(repo: Path, tag: Text, development: Text) -> Sources:
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise ValueError("Stable source must be an exact vX.Y.Z release tag")
    release = resolve(repo, f"refs/tags/{tag}")
    metadata = project_metadata(repo, release)
    if metadata["version"] != tag.removeprefix("v"):
        raise ValueError("Release tag and package version disagree")
    configuration = tomllib.loads((repo / "stable-docs.toml").read_text())
    stable = release
    if tag in configuration["backports"]:
        correction = configuration["backports"][tag]
        recorded = correction["source"]
        if not re.fullmatch(r"[0-9a-f]{40}", recorded):
            raise ValueError(
                "Documentation backport source must be an immutable commit SHA"
            )
        stable = resolve(repo, recorded)
        fetch_ref = correction["fetch_ref"]
        if not re.fullmatch(r"refs/(?:tags/[^\s:]+|pull/[1-9]\d*/head)", fetch_ref):
            raise ValueError(
                "Documentation backport fetch ref must be a tag or retained PR ref"
            )
        reachable = subprocess.run(  # noqa: S603 - Fixed Git command, no shell.
            (  # noqa: S607 - Git is supplied by the toolchain.
                "git",
                "-C",
                str(repo),
                "merge-base",
                "--is-ancestor",
                stable,
                resolve(repo, fetch_ref),
            ),
            check=False,
        )
        if reachable.returncode != 0:
            raise ValueError(
                "Documentation backport source is not reachable from its fetch ref"
            )
        if (
            git(repo, "rev-parse", f"{release}:src/client_query_cache")
            != git(repo, "rev-parse", f"{stable}:src/client_query_cache")
            or executable_examples(repo, release) != executable_examples(repo, stable)
            or metadata != project_metadata(repo, stable)
        ):
            raise ValueError(
                "Documentation backport differs from the released runtime, "
                "examples or project metadata"
            )
    return Sources(
        release=release,
        stable=stable,
        development=resolve(repo, development),
        version=metadata["version"],
    )


def extract_corpus(repo: Path, revision: Text, destination: Path) -> None:
    files = tuple(
        name
        for name in git(
            repo,
            "ls-tree",
            "-r",
            "--name-only",
            revision,
            "docs/user",
            "examples",
            "zensical.toml",
        )
        .decode()
        .splitlines()
        if name.startswith("docs/user/")
        or name in {"zensical.toml", "examples/README.md"}
        or (name.startswith("examples/") and name.endswith(".py"))
    )
    if "zensical.toml" not in files or "docs/user/index.md" not in files:
        raise ValueError(
            "Documentation source lacks the public guide layout; "
            "record a reviewed release backport"
        )
    destination.mkdir()
    with tarfile.open(
        fileobj=io.BytesIO(git(repo, "archive", revision, "--", *files))
    ) as archive:
        archive.extractall(destination, filter="data")


def edition_config(
    corpus: Path, revision: Text, export_policy: Table, *, stable: bool
) -> Path:
    configuration = tomllib.loads((corpus / "zensical.toml").read_text())
    project = table(configuration["project"])
    project["strict"] = True
    project["site_dir"] = str(corpus / "output")
    table(project["plugins"])["llmstxt"] = export_policy
    theme = table(project["theme"])
    try:
        features = cast("list[Text]", theme["features"])
    except KeyError:
        features = []
        theme["features"] = features
    if "content.action.copy" not in features:
        features.append("content.action.copy")
    if "extra" not in project:
        project["extra"] = {}
    table(project["extra"])["version"] = {"provider": "mike"}
    table(table(table(project["markdown_extensions"])["pymdownx"])["snippets"])[
        "base_path"
    ] = [str(corpus)]
    repository = project["repo_url"]
    hosted_base = cast("Text", project["site_url"]).rstrip("/") + "/"
    edition = "stable" if stable else "dev"
    for page in (*corpus.glob("docs/user/**/*.md"), corpus / "examples/README.md"):
        text = re.sub(
            re.escape(hosted_base) + r"(?!stable/|dev/)",
            hosted_base + edition + "/",
            page.read_text(),
        )
        if stable:
            for kind in ("tree", "blob"):
                text = text.replace(
                    f"{repository}/{kind}/main", f"{repository}/{kind}/{revision}"
                )
            text = text.replace(f"]({repository})", f"]({repository}/tree/{revision})")
        page.write_text(text)
    path = corpus / "zensical.toml"
    path.write_text(tomli_w.dumps(configuration))
    return path


def run(cwd: Path, *arguments: Text) -> None:
    subprocess.run(arguments, cwd=cwd, check=True)  # noqa: S603 - Fixed CLI names, no shell.


def root_redirects(development: Path, destination: Path) -> None:
    configuration = tomllib.loads((development / "zensical.toml").read_text())
    project = table(configuration["project"])

    def target(page: Text) -> Text:
        if not (destination / "stable/docs/user" / page.partition("#")[0]).is_file():
            return "stable/index.md"
        return "stable/" + page

    mappings = {
        page.relative_to(development / "docs/user").as_posix(): target(
            page.relative_to(development / "docs/user").as_posix()
        )
        for page in development.glob("docs/user/**/*.md")
        if page != development / "docs/user/index.md"
    }
    for source, page in table(
        table(table(project["plugins"])["redirects"])["redirect_maps"]
    ).items():
        mappings[source] = target(cast("Text", page))
    redirect_corpus = destination / "redirect-source"
    (redirect_corpus / "docs").mkdir(parents=True)
    (redirect_corpus / "docs/index.md").write_text("# Documentation\n")
    shutil.copytree(destination / "stable/docs/user", redirect_corpus / "docs/stable")
    redirect_configuration = {
        "project": {
            "site_name": project["site_name"],
            "site_url": project["site_url"],
            "docs_dir": "docs",
            "site_dir": str(redirect_corpus / "output"),
            "strict": True,
            "theme": {"font": False},
            "plugins": {"redirects": {"redirect_maps": mappings}},
            "markdown_extensions": table(
                tomllib.loads((destination / "stable/zensical.toml").read_text())[
                    "project"
                ]
            )["markdown_extensions"],
        }
    }
    (redirect_corpus / "zensical.toml").write_text(
        tomli_w.dumps(redirect_configuration)
    )
    run(redirect_corpus, "zensical", "build", "--clean", "--strict")


def replace_artifact(artifact: Path, output: Path) -> None:
    with TemporaryDirectory(prefix=".docs-artifact-", dir=output.parent) as temporary:
        staging = Path(temporary)
        replacement = staging / "new"
        shutil.copytree(artifact, replacement)
        backup = output.with_name(f".docs-previous-{uuid4().hex}")
        if output.exists():
            output.rename(backup)
        try:
            replacement.rename(output)
        except OSError:
            if backup.exists():
                backup.rename(output)
            raise
        if backup.exists():
            backup.rename(staging / "previous")


def assemble(repo: Path, sources: Sources, output: Path) -> None:
    if output.is_symlink():
        raise ValueError("Artifact output must not be a symbolic link")
    with TemporaryDirectory(prefix="docs-editions-") as temporary:
        workspace = Path(temporary)
        run(workspace, "git", "init", "-q")
        for key, value in (
            ("commit.gpgsign", "false"),
            ("user.name", "Documentation artifact"),
            ("user.email", "docs@example.invalid"),
        ):
            run(workspace, "git", "config", "--local", key, value)
        run(
            workspace,
            "git",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "Initialize disposable documentation artifact",
        )
        for edition, revision in (
            ("stable", sources["stable"]),
            ("dev", sources["development"]),
        ):
            extract_corpus(repo, revision, workspace / edition)
        development_configuration = tomllib.loads(
            (workspace / "dev/zensical.toml").read_text()
        )
        export_policy = table(
            table(table(development_configuration["project"])["plugins"])["llmstxt"]
        )
        stable_configuration = tomllib.loads(
            (workspace / "stable/zensical.toml").read_text()
        )
        stable_plugins = table(table(stable_configuration["project"])["plugins"])
        try:
            stable_export_policy = table(stable_plugins["llmstxt"])
        except KeyError:
            stable_export_policy = export_policy
        for edition, revision, title, edition_export_policy in (
            (
                "stable",
                sources["stable"],
                f"Latest release ({sources['version']})",
                stable_export_policy,
            ),
            ("dev", sources["development"], "Development (main)", export_policy),
        ):
            corpus = workspace / edition
            configuration = edition_config(
                corpus, revision, edition_export_policy, stable=edition == "stable"
            )
            run(
                corpus,
                "mike",
                "deploy",
                edition,
                "--title",
                title,
                "--config-file",
                str(configuration),
                "--branch",
                "docs-artifact",
                "--ignore-remote-status",
            )
        run(
            workspace / "dev",
            "mike",
            "set-default",
            "stable",
            "--config-file",
            str(workspace / "dev/zensical.toml"),
            "--branch",
            "docs-artifact",
            "--ignore-remote-status",
        )
        artifact = workspace / "artifact"
        artifact.mkdir()
        with tarfile.open(
            fileobj=io.BytesIO(git(workspace, "archive", "docs-artifact"))
        ) as archive:
            archive.extractall(artifact, filter="data")
        root_redirects(workspace / "dev", workspace)
        for entry in (workspace / "redirect-source/output").iterdir():
            if entry.name in {"index.html", "stable"}:
                continue
            if entry.is_dir():
                shutil.copytree(entry, artifact / entry.name, dirs_exist_ok=True)
            else:
                shutil.copy2(entry, artifact / entry.name)
        shutil.copy2(artifact / "stable/llms.txt", artifact / "llms.txt")
        try:
            full_output = stable_export_policy["full_output"]
        except KeyError:
            full_output = None
        if full_output is not None:
            full_path = Path(cast("Text", full_output))
            (artifact / full_path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(artifact / "stable" / full_path, artifact / full_path)
        replace_artifact(artifact, output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stable_tag")
    parser.add_argument("--development-ref", default="HEAD")
    arguments = parser.parse_args()
    repo = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").decode().strip())
    sources = select_sources(repo, arguments.stable_tag, arguments.development_ref)
    print(
        f"Release: {sources['release']}\n"
        f"Stable docs: {sources['stable']}\n"
        f"Development: {sources['development']}",
        flush=True,
    )
    assemble(repo, sources, repo / "site")


if __name__ == "__main__":
    main()
