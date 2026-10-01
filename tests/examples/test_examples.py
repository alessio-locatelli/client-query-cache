import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from tests.conftest import MongoDbUri

pytestmark = pytest.mark.integration

REPOSITORY = Path(__file__).parents[2]


@pytest.mark.timeout(300)
@pytest.mark.parametrize(
    "name",
    ["requests_cache_example.py", "celery_example.py", "py_abac_example.py"],
    ids=["requests-cache", "celery", "py-abac"],
)
def test_example_runs(name: str, mongodb_uri: MongoDbUri) -> None:
    uv = shutil.which("uv")
    assert uv is not None
    completed = subprocess.run(  # noqa: S603
        (uv, "run", f"examples/{name}"),
        cwd=REPOSITORY,
        env={**os.environ, "MONGODB_URI": mongodb_uri},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, (
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
