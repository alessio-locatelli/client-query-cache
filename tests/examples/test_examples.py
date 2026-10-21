import os
import re
import shutil
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

    from tests.conftest import MongoDbUri

pytestmark = pytest.mark.integration

REPOSITORY = Path(__file__).parents[2]
SERVED_WORKERS = 2
STARTED = re.compile(r"worker (\d+): cache manager started")
CLOSED = re.compile(r"worker (\d+): cache manager closed before client")


def _uv() -> str:
    uv = shutil.which("uv")
    assert uv is not None
    return uv


def _refused(port: int) -> bool:
    with socket.socket() as probe:
        return probe.connect_ex(("127.0.0.1", port)) != 0


@pytest.fixture
def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


# uv --locked defaults to the inherited UV_LOCKED. These PEP 723 scripts resolve
# independently of the project lockfile, just like typecheck-examples in justfile.
@pytest.fixture
def served_catalogue(
    mongodb_uri: MongoDbUri, free_port: int
) -> Iterator[tuple[subprocess.Popen[str], int]]:
    process = subprocess.Popen(  # noqa: S603 - Run the repository example with a resolved uv executable and no shell.
        (
            _uv(),
            "run",
            "examples/fastapi_catalogue_example.py",
            "--serve",
            "--workers",
            str(SERVED_WORKERS),
            "--port",
            str(free_port),
        ),
        cwd=REPOSITORY,
        env={
            **os.environ,
            "MONGODB_URI": mongodb_uri,
            "CONTENT_CACHE_ENABLED": "true",
            "UV_LOCKED": "0",
        },
        stdout=subprocess.PIPE,
        text=True,
    )
    yield process, free_port
    process.kill()
    process.wait()


@pytest.mark.timeout(300)
@pytest.mark.parametrize(
    "name",
    [
        "requests_cache_example.py",
        "celery_example.py",
        "py_abac_example.py",
        "aiohttp_client_cache_example.py",
        "eve_example.py",
        "fastapi_catalogue_example.py",
        "fastapi_minimal_example.py",
        "fastapi_shared_example.py",
    ],
    ids=[
        "requests-cache",
        "celery",
        "py-abac",
        "aiohttp-client-cache",
        "eve",
        "fastapi",
        "fastapi-minimal",
        "fastapi-shared",
    ],
)
def test_example_runs(name: str, mongodb_uri: MongoDbUri) -> None:
    completed = subprocess.run(  # noqa: S603 - Example names come from the fixed parametrized test cases; no shell is used.
        (_uv(), "run", f"examples/{name}"),
        cwd=REPOSITORY,
        env={**os.environ, "MONGODB_URI": mongodb_uri, "UV_LOCKED": "0"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, (
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )


@pytest.mark.timeout(300)
def test_catalogue_serves_from_independent_workers(
    served_catalogue: tuple[subprocess.Popen[str], int],
) -> None:
    process, port = served_catalogue
    assert process.stdout is not None
    startup = "".join(process.stdout.readline() for _ in range(SERVED_WORKERS))
    while _refused(port):
        time.sleep(0.05)  # pragma: lax no cover (workers listen after lifespan startup)

    with pytest.raises(urllib.error.HTTPError) as rejected:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/products/shared")
    process.send_signal(signal.SIGINT)
    remaining, _ = process.communicate(timeout=60)

    started = set(STARTED.findall(startup))
    assert len(started) == SERVED_WORKERS
    assert rejected.value.code == 401
    assert process.returncode == 0
    assert set(CLOSED.findall(remaining)) == started
