from __future__ import annotations

import datetime
import random
import zlib
from typing import TYPE_CHECKING, TypedDict

from bson.decimal128 import Decimal128

from client_query_cache._core.codec import encode_value

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from pymongo import MongoClient

    from client_query_cache._types import NonNegativeInt, PositiveInt

_EPOCH = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
_TAG_VALUES = 512
_TAGS_PER_DOCUMENT = 4
_INSERT_BATCH = 512


class Profile(TypedDict):
    documents: PositiveInt
    payload_bytes: PositiveInt
    read: str


class DatasetSummary(TypedDict):
    documents: PositiveInt
    entry_min_bytes: PositiveInt
    entry_max_bytes: PositiveInt
    entry_total_bytes: PositiveInt


def catalogue(
    seed: int, profile: Profile, categories: PositiveInt
) -> Iterator[dict[str, object]]:
    generator = random.Random(seed)
    for index in range(profile["documents"]):
        yield {
            "_id": index,
            "sku": f"SKU-{index:06d}",
            "revision": 0,
            "attributes": {
                "category": index % categories,
                "price": Decimal128(f"{generator.randrange(100, 100_000) / 100:.2f}"),
                "tags": [
                    f"tag-{generator.randrange(_TAG_VALUES)}"
                    for _ in range(_TAGS_PER_DOCUMENT)
                ],
                "dimensions": {
                    "width": generator.random(),
                    "height": generator.random(),
                    "depth": generator.random(),
                },
                "updated": _EPOCH + datetime.timedelta(seconds=index),
            },
            "payload": generator.randbytes(profile["payload_bytes"] // 2).hex(),
        }


def seed_catalogue(
    client: MongoClient[dict[str, object]],
    *,
    database: str,
    collection: str,
    seed: int,
    profile: Profile,
    categories: PositiveInt,
) -> DatasetSummary:
    client.drop_database(database)
    target = client[database][collection]
    sizes: list[NonNegativeInt] = []
    batch: list[dict[str, object]] = []
    for document in catalogue(seed, profile, categories):
        sizes.append(len(encode_value(document)))
        batch.append(document)
        if len(batch) == _INSERT_BATCH:
            target.insert_many(batch)
            batch = []
    if batch:
        target.insert_many(batch)
    return {
        "documents": profile["documents"],
        "entry_min_bytes": min(sizes),
        "entry_max_bytes": max(sizes),
        "entry_total_bytes": sum(sizes),
    }


def checksum(document: Mapping[str, object] | None) -> NonNegativeInt:
    if document is None:
        message = "scheduled catalogue document disappeared"
        raise LookupError(message)
    payload = document["payload"]
    assert isinstance(payload, str)
    revision = document["revision"]
    assert isinstance(revision, int)
    return zlib.crc32(payload.encode()) ^ revision
