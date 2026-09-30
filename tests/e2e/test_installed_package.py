import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, NewType

import pytest

if TYPE_CHECKING:
    from tests.conftest import MongoDbUri

pytestmark = pytest.mark.e2e

Command = NewType("Command", tuple[str, ...])


def run_command(
    command: Command,
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> None:
    subprocess.run(command, check=True, cwd=cwd, env=env)  # noqa: S603


@pytest.fixture(scope="session")
def installed_python(tmp_path_factory: pytest.TempPathFactory) -> Path:
    uv = shutil.which("uv")
    assert uv is not None
    repository = Path(__file__).parents[2]
    build_directory = tmp_path_factory.mktemp("wheel")
    environment_directory = tmp_path_factory.mktemp("installed")
    run_command(
        Command((uv, "build", "--wheel", "--out-dir", str(build_directory))),
        cwd=repository,
    )
    wheel = next(build_directory.glob("*.whl"))
    run_command(
        Command((uv, "venv", "--python", sys.executable, str(environment_directory)))
    )
    python = environment_directory / "bin" / "python"
    run_command(Command((uv, "pip", "install", "--python", str(python), str(wheel))))
    return python


def test_installed_public_api_uses_disposable_mongodb(
    installed_python: Path,
    mongodb_uri: MongoDbUri,
    tmp_path: Path,
) -> None:
    database_name = f"e2e_{uuid.uuid4().hex}"
    collection_name = "records"
    environment = os.environ.copy()
    environment.update(
        {
            "MONGODB_TEST_URI": mongodb_uri,
            "MONGODB_TEST_DATABASE": database_name,
            "MONGODB_TEST_COLLECTION": collection_name,
        }
    )
    environment.pop("PYTHONPATH", None)
    script = """
import os

from pymongo import MongoClient

from client_query_cache import CacheManager
from client_query_cache.asynchronous import (
    CacheManager as AsyncCacheManager,
    CachedCollection as AsyncCachedCollection,
    CachedDatabase as AsyncCachedDatabase,
)

uri = os.environ["MONGODB_TEST_URI"]
database_name = os.environ["MONGODB_TEST_DATABASE"]
collection_name = os.environ["MONGODB_TEST_COLLECTION"]
with MongoClient(uri) as client, CacheManager(client) as cache_manager:
    collection = client[database_name][collection_name]
    cached_collection = cache_manager.cached(collection)
    collection.insert_one({"_id": "independent-write", "value": 42})
    document = cached_collection.find_one({"_id": "independent-write"})
    assert document == {"_id": "independent-write", "value": 42}
    client.drop_database(database_name)
"""

    run_command(
        Command((str(installed_python), "-I", "-c", script)),
        cwd=tmp_path,
        env=environment,
    )
