import os
import re
import shutil
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, NewType

import pytest
from pymongo import MongoClient

from client_query_cache._types import BsonDict

if TYPE_CHECKING:
    from collections.abc import Iterator

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
import asyncio
import os

from pymongo import AsyncMongoClient, MongoClient
from pymongo.synchronous.cursor import Cursor
from pymongo.synchronous.command_cursor import CommandCursor
from pymongo.asynchronous.cursor import AsyncCursor
from pymongo.asynchronous.command_cursor import AsyncCommandCursor

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
    cached_collection = cache_manager.get_cached_collection(collection)
    collection.insert_one({"_id": "independent-write", "value": 42})
    document = cached_collection.find_one({"_id": "independent-write"})
    assert document == {"_id": "independent-write", "value": 42}
    cursor = cached_collection.find({})
    assert isinstance(cursor, Cursor)
    assert list(cursor) == [document]
    aggregate = cached_collection.aggregate([])
    assert isinstance(aggregate, CommandCursor)
    assert aggregate.to_list() == [document]
    client.drop_database(database_name)

async def consume():
    async with AsyncMongoClient(uri) as client, AsyncCacheManager(client) as manager:
        raw = client[database_name][collection_name]
        await raw.insert_one({"_id": "async-write", "value": 42})
        cached = manager.get_cached_collection(raw)
        cursor = cached.find({})
        assert isinstance(cursor, AsyncCursor)
        assert [row async for row in cursor] == [{"_id": "async-write", "value": 42}]
        aggregate = await cached.aggregate([])
        assert isinstance(aggregate, AsyncCommandCursor)
        assert await aggregate.to_list() == [{"_id": "async-write", "value": 42}]
        await client.drop_database(database_name)

asyncio.run(consume())
"""

    run_command(
        Command((str(installed_python), "-I", "-c", script)),
        cwd=tmp_path,
        env=environment,
    )


@pytest.fixture(params=("synchronous", "asyncio", "usage-sync", "usage-async"))
def documented_program(
    request: pytest.FixtureRequest, mongodb_uri: MongoDbUri
) -> Iterator[str]:
    repository = Path(__file__).parents[2]
    database = f"documented_{uuid.uuid4().hex}"
    if request.param in {"synchronous", "asyncio"}:
        guide = repository / f"docs/user/getting-started/{request.param}.md"
        script = re.findall(r"```python\n(.*?)```", guide.read_text(), re.DOTALL)[0]
    else:
        guide = repository / "docs/user/usage/cached-reads.md"
        blocks = re.findall(r"```python\n(.*?)```", guide.read_text(), re.DOTALL)
        if request.param == "usage-sync":
            script = "from pymongo import MongoClient\n"
            script += "from client_query_cache import CacheManager\n"
            script += 'with (MongoClient("mongodb://localhost:27017") as client,\n'
            script += "      CacheManager(client) as cache_manager):\n"
            script += textwrap.indent(blocks[0] + blocks[1], "    ")
        else:
            script = "import asyncio\nfrom pymongo import AsyncMongoClient\n"
            script += "from client_query_cache.asynchronous import CacheManager\n"
            script += "async def main():\n"
            script += "    async with (\n"
            script += (
                '        AsyncMongoClient("mongodb://localhost:27017") as client,\n'
            )
            script += "        CacheManager(client) as cache_manager):\n"
            script += textwrap.indent(
                'cached_products = cache_manager["shop"]["products"]\n', "        "
            )
            script += textwrap.indent(blocks[2], "        ")
            script += "asyncio.run(main())\n"
        with MongoClient[BsonDict](mongodb_uri) as client:
            client[database]["products"].insert_many(
                [
                    {"_id": number, "status": "active", "name": str(number)}
                    for number in range(12)
                ]
            )
    script = script.replace('"mongodb://localhost:27017"', repr(str(mongodb_uri)))
    script = script.replace('"client_query_cache_tutorial"', repr(database))
    script = script.replace('"shop"', repr(database))
    yield script
    with MongoClient[BsonDict](mongodb_uri) as client:
        client.drop_database(database)


def test_documented_cursor_programs(
    documented_program: str, installed_python: Path, tmp_path: Path
) -> None:
    run_command(
        Command((str(installed_python), "-I", "-c", documented_program)), cwd=tmp_path
    )
