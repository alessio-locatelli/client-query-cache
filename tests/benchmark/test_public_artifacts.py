from __future__ import annotations

import sys
from importlib.metadata import PathDistribution
from typing import TYPE_CHECKING

import pytest

from development.benchmarks import public_shared_cache as harness

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.fixture
def installed_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    site_packages = tmp_path / "uv-cache" / "site-packages"
    metadata = site_packages / "client_query_cache-0.0.0.dist-info"
    metadata.mkdir(parents=True)
    package = site_packages / "client_query_cache"
    package.mkdir()
    (package / "__init__.py").touch()
    (package / "_shared_index.abi3.so").touch()
    monkeypatch.setattr(
        harness, "distribution", lambda _name: PathDistribution(metadata)
    )
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "isolated-venv"))
    return package


def test_installed_artifacts_can_live_in_uv_cache(installed_package: Path) -> None:
    harness._validate_installed_artifacts(
        {
            "library": str(installed_package / "__init__.py"),
            "extension": str(installed_package / "_shared_index.abi3.so"),
        }
    )


@pytest.mark.parametrize("component", ["library", "extension"])
def test_artifacts_outside_installed_package_are_rejected(
    installed_package: Path, tmp_path: Path, component: str
) -> None:
    artifacts = {
        "library": str(installed_package / "__init__.py"),
        "extension": str(installed_package / "_shared_index.abi3.so"),
    }
    artifacts[component] = str(tmp_path / "checkout" / "src" / "client_query_cache")
    with pytest.raises(ValueError, match=f"Benchmark {component} artifact .*outside"):
        harness._validate_installed_artifacts(artifacts)
