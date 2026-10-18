# ruff: noqa: PLC2701 - Reuse the existing public benchmark window without duplicating it.
import json
import pathlib
import sys

from pymongo import MongoClient

from benchmarks.public_shared_cache import _DOCUMENT_BYTES, _HOT_KEYS, _run_window
from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits


def main() -> None:
    windows = []
    with (
        IsolatedReplicaSet(ResourceLimits(cpus=2.0, memory="1g")) as replica,
        MongoClient(replica.uri) as client,
    ):
        for model in ("sync", "async"):
            client.drop_database("public_shared_cache")
            client.public_shared_cache.items.insert_many(
                {"_id": i, "payload": "x" * _DOCUMENT_BYTES} for i in range(_HOT_KEYS)
            )
            windows.append(
                _run_window(
                    replica, model, "hot", "shared", 100000, profile_directory=None
                )
            )
    with pathlib.Path(sys.argv[1]).open("w", encoding="utf-8") as output:
        json.dump(windows, output, indent=2)


if __name__ == "__main__":
    main()
