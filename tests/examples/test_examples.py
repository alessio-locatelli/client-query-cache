import hashlib
import json
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


def _source_extension_digests() -> dict[Path, str]:
    package = REPOSITORY / "src" / "client_query_cache"
    return {
        extension: hashlib.sha256(extension.read_bytes()).hexdigest()
        for extension in package.glob("_shared_index.abi3.so")
    }


@pytest.fixture
def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@pytest.fixture(scope="module")
def example_env() -> Iterator[dict[str, str]]:
    # A wheel-timing run can put its artifact on PYTHONPATH. The examples resolve
    # their own checkout dependency and do not use the project's lockfile.
    env = {**os.environ, "UV_LOCKED": "0"}
    env.pop("PYTHONPATH", None)
    source_digests = _source_extension_digests()
    yield env
    assert _source_extension_digests() == source_digests


@pytest.fixture
def served_catalogue(
    mongodb_uri: MongoDbUri, free_port: int, example_env: dict[str, str]
) -> Iterator[tuple[subprocess.Popen[str], int]]:
    process = subprocess.Popen(  # noqa: S603 - Run the repository example with a resolved uv executable and no shell.
        (
            _uv(),
            "run",
            "docs/examples/fastapi_catalogue_example.py",
            "--serve",
            "--workers",
            str(SERVED_WORKERS),
            "--port",
            str(free_port),
        ),
        cwd=REPOSITORY,
        env={
            **example_env,
            "MONGODB_URI": mongodb_uri,
            "CONTENT_CACHE_ENABLED": "true",
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
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
        "cachier_example.py",
        "cachier_async_example.py",
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
        "cachier",
        "cachier-async",
        "celery",
        "py-abac",
        "aiohttp-client-cache",
        "eve",
        "fastapi",
        "fastapi-minimal",
        "fastapi-shared",
    ],
)
def test_example_runs(
    name: str, mongodb_uri: MongoDbUri, example_env: dict[str, str]
) -> None:
    completed = subprocess.run(  # noqa: S603 - Example names come from the fixed parametrized test cases; no shell is used.
        (_uv(), "run", f"docs/examples/{name}"),
        cwd=REPOSITORY,
        env={**example_env, "MONGODB_URI": mongodb_uri},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, (
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )


@pytest.mark.timeout(300)
def test_example_environment_imports_the_checkout_wheel(
    example_env: dict[str, str],
    tmp_path: Path,
) -> None:
    sync = (
        _uv(),
        "sync",
        "--script",
        "docs/examples/fastapi_minimal_example.py",
        "--output-format",
        "json",
    )
    fresh_environment = tmp_path / "example"
    # The warm sync must install from cache into an empty environment.
    # Copy linking supports a temporary environment on another filesystem.
    fresh_env: dict[str, str | Path] = {
        **example_env,
        "VIRTUAL_ENV": fresh_environment,
        "UV_LINK_MODE": "copy",
    }
    for extra_args, env in (
        ((), example_env),
        (("--active", "--no-build-package", "client-query-cache"), fresh_env),
    ):
        synced = subprocess.run(  # noqa: S603 - Sync a fixed repository script with the resolved uv executable.
            (*sync, *extra_args),
            cwd=REPOSITORY,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert synced.returncode == 0, synced.stderr
    python = json.loads(synced.stdout)["sync"]["environment"]["python"]["path"]
    assert Path(python).parent.parent == fresh_environment
    checked = subprocess.run(  # noqa: S603 - Use the synced environment interpreter and a fixed identity check.
        (
            python,
            "-c",
            """
import base64
import hashlib
import json
import sys
from importlib.metadata import distribution
from pathlib import Path

wheel = distribution("client-query-cache")
origin = json.loads(wheel.read_text("direct_url.json"))
assert origin["url"] == Path(sys.argv[1]).as_uri(), origin
extension = next(file for file in wheel.files if file.name == "_shared_index.abi3.so")
installed_extension = extension.locate()
digest = hashlib.sha256(installed_extension.read_bytes()).digest()
assert extension.hash.mode == "sha256"
assert base64.urlsafe_b64encode(digest).decode().rstrip("=") == extension.hash.value

import client_query_cache
from client_query_cache import _shared_index

assert Path(client_query_cache.__file__).parent == installed_extension.parent
assert Path(_shared_index.__file__) == installed_extension
""",
            str(REPOSITORY.resolve()),
        ),
        cwd=REPOSITORY,
        env=example_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode == 0, checked.stderr


@pytest.mark.timeout(300)
def test_catalogue_serves_from_independent_workers(
    served_catalogue: tuple[subprocess.Popen[str], int],
) -> None:
    process, port = served_catalogue
    assert process.stdout is not None
    startup: list[str] = []
    started: set[str] = set()
    while len(started) < SERVED_WORKERS:
        line = process.stdout.readline()
        assert line, (
            f"Catalogue output ended before both workers started.\n{''.join(startup)}"
        )
        startup.append(line)
        started.update(STARTED.findall(line))
    while True:
        assert process.poll() is None, (
            f"Catalogue exited before listening (exit {process.returncode}).\n"
            f"{''.join(startup)}{process.stdout.read()}"
        )
        if not _refused(port):
            break
        time.sleep(0.05)  # pragma: lax no cover (workers listen after lifespan startup)

    with pytest.raises(urllib.error.HTTPError) as rejected:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/products/shared")
    process.send_signal(signal.SIGINT)
    remaining, _ = process.communicate(timeout=60)

    assert rejected.value.code == 401
    assert process.returncode == 0
    assert set(CLOSED.findall(remaining)) == started
