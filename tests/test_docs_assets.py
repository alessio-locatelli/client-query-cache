from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def documentation_output(tmp_path: Path) -> Path:
    (tmp_path / "README.md").write_text("Repository-only content")
    (tmp_path / "zensical.toml").write_text(
        '[project]\nsite_dir = "site"\n'
        'site_url = "https://example.com/client-query-cache/"\n'
    )
    site = tmp_path / "site"
    (site / "guide").mkdir(parents=True)
    (site / "assets").mkdir()
    (site / "assets" / "figure.svg").write_text("<svg></svg>")
    (site / "index.html").write_text("<h1>Home</h1>")
    return tmp_path


@pytest.mark.parametrize(
    ("html", "valid"),
    [
        pytest.param('<img src="../assets/figure.svg">', True, id="relative-asset"),
        pytest.param(
            '<img src="/client-query-cache/assets/figure.svg?cache=1">',
            True,
            id="project-subpath",
        ),
        pytest.param('<a href="../">Home</a>', True, id="directory-page"),
        pytest.param(
            '<a href="../../README.md">Repository</a>', False, id="outside-site"
        ),
        pytest.param(
            '<img src="/assets/figure.svg">', False, id="outside-project-subpath"
        ),
        pytest.param('<a href="#heading">Heading</a>', True, id="heading"),
        pytest.param('<img src="https://example.com/remote.svg">', True, id="remote"),
        pytest.param(
            '<img src="//example.com/remote.svg">', True, id="protocol-relative"
        ),
        pytest.param('<img src="data:image/svg+xml,test">', True, id="inline"),
        pytest.param("<input disabled>", True, id="unrelated-attribute"),
        pytest.param('<img src="">', True, id="empty-source"),
        pytest.param('<img src="../assets/missing.svg">', False, id="missing-image"),
        pytest.param('<link href="../assets/missing.css">', False, id="missing-style"),
        pytest.param(
            '<script src="../assets/missing.js"></script>', False, id="missing-script"
        ),
        pytest.param(
            '<a href="../missing.pdf">Download</a>', False, id="missing-download"
        ),
    ],
)
def test_documentation_assets_reject_missing_targets(
    documentation_output: Path, html: str, *, valid: bool
) -> None:
    (documentation_output / "site" / "guide" / "index.html").write_text(html)
    completed = subprocess.run(  # noqa: S603 — Execute the fixed repository checker.
        (sys.executable, str(Path("scripts/check_docs_assets.py").resolve())),
        cwd=documentation_output,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == (0 if valid else 1)
    assert (b"missing local target" in completed.stderr) is not valid


def test_documentation_assets_require_built_pages(tmp_path: Path) -> None:
    (tmp_path / "zensical.toml").write_text(
        '[project]\nsite_dir = "site"\nsite_url = "https://example.com/"\n'
    )
    completed = subprocess.run(  # noqa: S603 — Execute the fixed repository checker.
        (sys.executable, str(Path("scripts/check_docs_assets.py").resolve())),
        cwd=tmp_path,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 1
    assert b"contains no HTML pages" in completed.stderr
