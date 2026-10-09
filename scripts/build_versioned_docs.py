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

type Text = str
type Table = dict[Text, object]


def table(value: object) -> Table:
    return cast("Table", value)


class Sources(TypedDict):
    stable: Text
    development: Text
    version: Text


def git(repo: Path, *arguments: Text) -> bytes:
    # Python 3.14: https://docs.python.org/3.14/library/subprocess.html
    # check=True: The default is false. We override it because failed commands must
    # abort assembly or benchmark preparation.
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


def select_sources(repo: Path, tag: Text, development: Text) -> Sources:
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise ValueError("Stable source must be an exact vX.Y.Z release tag")
    stable = resolve(repo, f"refs/tags/{tag}")
    metadata = table(
        tomllib.loads(git(repo, "show", f"{stable}:pyproject.toml").decode())["project"]
    )
    if metadata["version"] != tag.removeprefix("v"):
        raise ValueError("Release tag and package version disagree")
    return Sources(
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
        raise ValueError("Documentation source lacks the public guide layout")
    destination.mkdir()
    with tarfile.open(
        fileobj=io.BytesIO(git(repo, "archive", revision, "--", *files))
    ) as archive:
        archive.extractall(destination, filter="data")


def edition_config(corpus: Path, revision: Text, *, stable: bool) -> Table:
    configuration = tomllib.loads((corpus / "zensical.toml").read_text())
    project = table(configuration["project"])
    export_policy = table(table(project["plugins"])["llmstxt"])
    # Zensical 0.0.68:
    # https://github.com/zensical/zensical/blob/v0.0.68/python/zensical/config.py
    # strict: The default is inherited from the extracted config. We override it because
    # publication must fail on warnings, including broken links.
    project["strict"] = True
    project["site_dir"] = str(corpus / "output")
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
    (corpus / "zensical.toml").write_text(tomli_w.dumps(configuration))
    return export_policy


def run(cwd: Path, *arguments: Text) -> None:
    # check=True: The default is false. We override it because failed commands must
    # abort assembly or benchmark preparation.
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
            # strict: The default is false. We override it because root redirects must
            # also fail on warnings.
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
    # Zensical 0.0.68:
    # https://github.com/zensical/zensical/blob/v0.0.68/python/zensical/main.py
    # --clean: The default is false. We override it because publication checks must
    # rebuild without reusing the prior cache.
    run(redirect_corpus, "zensical", "build", "--clean")


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
        # Git 2.55.0: https://git-scm.com/docs/git-config
        # For --local below: The default is GIT_CONFIG when set, otherwise
        # repository-local writes. We override it because external-file redirection must
        # be rejected before configuring this disposable repository.
        # For commit.gpgsign=false: The default is inherited Git configuration,
        # including user/system scopes. We override it because assembly must not request
        # a developer's signing key.
        # init -q and commit -q below: The default is normal progress output. We
        # override it because contributor builds should emphasize diagnostics.
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
        export_policies = {
            edition: edition_config(
                workspace / edition, revision, stable=edition == "stable"
            )
            for edition, revision in (
                ("stable", sources["stable"]),
                ("dev", sources["development"]),
            )
        }
        for edition, title in (
            ("stable", f"Latest release ({sources['version']})"),
            ("dev", "Development (main)"),
        ):
            corpus = workspace / edition
            run(
                corpus,
                "mike",
                "deploy",
                edition,
                "--title",
                title,
                # Mike 2d4ad799:
                # https://github.com/squidfunk/mike/blob/2d4ad799442f4592db8ad53b179bfb33db8c69ac/mike/driver.py
                # --branch: The default is inherited remote_branch, otherwise gh-pages.
                # We override it because assembly commits only to a disposable artifact
                # branch.
                # --ignore-remote-status: The default is checking the remote branch. We
                # override it because this assembly repository has no remote.
                "--branch",
                "docs-artifact",
                "--ignore-remote-status",
            )
        run(
            workspace / "dev",
            "mike",
            "set-default",
            "stable",
            # --branch: The default is inherited remote_branch, otherwise gh-pages. We
            # override it because the default edition must use the disposable artifact
            # branch.
            # --ignore-remote-status: The default is checking the remote branch. We
            # override it because this assembly repository has no remote.
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
        stable_export_policy = export_policies["stable"]
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
        f"Stable ({sources['version']}): {sources['stable']}\n"
        f"Development: {sources['development']}",
        flush=True,
    )
    assemble(repo, sources, repo / "site")


if __name__ == "__main__":
    main()
