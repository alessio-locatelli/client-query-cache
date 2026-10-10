# ruff: noqa: INP001, S603 - Standalone research launch smoke with fixed local commands.
from __future__ import annotations

import json
import multiprocessing
import os
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from importlib.metadata import version
from pathlib import Path

from pymongo import MongoClient

from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits
from research.shared_cache_launch.launch_owner import owner_from_environment

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[1]
_DATABASE = "launch_smoke"
_DOCUMENTS = 16
_REQUESTS = 40


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_for_port(port: int, deadline: float) -> None:
    while time.monotonic() < deadline:
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.1)
    message = f"server did not listen on {port}"
    raise TimeoutError(message)


def _drive(port: int) -> list[dict[str, object]]:
    responses = []
    for ordinal in range(_REQUESTS):
        key = ordinal % _DOCUMENTS
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/{key}", timeout=10
        ) as reply:
            responses.append(json.loads(reply.read()))
        time.sleep(0.05)
    return responses


def _summary(responses: list[dict[str, object]], socket_path: str) -> dict[str, object]:
    return {
        "requests": len(responses),
        "correct": all(
            response["id"] == ordinal % _DOCUMENTS
            for ordinal, response in enumerate(responses)
        ),
        "worker_pids": len({response["pid"] for response in responses}),
        "owner_incarnations": len({response["incarnation"] for response in responses}),
        "final_hits": sum(1 for response in responses[_DOCUMENTS:] if response["hits"]),
        "socket_removed": not Path(socket_path).exists(),
    }


def _environment(uri: str, directory: str) -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONPATH": f"{_ROOT}{os.pathsep}{_HERE}",
        "SHARED_CACHE_SOCKET": f"{directory}/owner.sock",
        "SHARED_CACHE_CAPABILITY": secrets.token_hex(32),
        "SHARED_CACHE_MONGODB_URI": uri,
        "SHARED_CACHE_DATABASE": _DATABASE,
    }


def gunicorn_smoke(uri: str) -> dict[str, object]:
    directory = tempfile.mkdtemp(prefix="gunicorn-smoke-")
    environment = _environment(uri, directory)
    port = _free_port()
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "gunicorn",
            "--config",
            str(_HERE / "gunicorn_conf.py"),
            "--bind",
            f"127.0.0.1:{port}",
            "wsgi_app:application",
        ],
        cwd=_HERE,
        env=environment,
    )
    try:
        _wait_for_port(port, time.monotonic() + 60)
        responses = _drive(port)
    finally:
        server.send_signal(signal.SIGTERM)
        server.wait(30)
    return {
        "gunicorn": version("gunicorn"),
        **_summary(responses, environment["SHARED_CACHE_SOCKET"]),
    }


def uvicorn_smoke(uri: str) -> dict[str, object]:
    directory = tempfile.mkdtemp(prefix="uvicorn-smoke-")
    environment = _environment(uri, directory)
    os.environ.update(environment)
    process, control = owner_from_environment(multiprocessing.get_context("spawn"))
    port = _free_port()
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "asgi_app:app",
            "--workers",
            "2",
            "--limit-max-requests",
            "5",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=_HERE,
        env=environment,
    )
    try:
        _wait_for_port(port, time.monotonic() + 60)
        responses = _drive(port)
    finally:
        server.send_signal(signal.SIGTERM)
        server.wait(30)
        control.send("close")
        control.recv()
        process.join(15)
    return {
        "uvicorn": version("uvicorn"),
        **_summary(responses, environment["SHARED_CACHE_SOCKET"]),
    }


def main() -> None:
    with IsolatedReplicaSet(ResourceLimits(cpus=1.0, memory="1g")) as replica:
        with MongoClient[dict[str, object]](replica.uri) as client:
            client[_DATABASE]["catalogue"].insert_many(
                {"_id": index, "payload": f"value-{index}"}
                for index in range(_DOCUMENTS)
            )
        print(json.dumps({"gunicorn": gunicorn_smoke(replica.uri)}, indent=1))
        print(json.dumps({"uvicorn": uvicorn_smoke(replica.uri)}, indent=1))


if __name__ == "__main__":
    main()
