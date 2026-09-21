from __future__ import annotations

import hashlib
from dataclasses import dataclass

import bson
from bson import ObjectId
from faker import Faker

from benchmarks.stream_cost.errors import BenchmarkConfigurationError


@dataclass(frozen=True, slots=True)
class DocumentSizeProfile:
    name: str
    target_bytes: int

    def __post_init__(self) -> None:
        if not self.name:
            message = "name must not be empty"
            raise BenchmarkConfigurationError(message)
        if self.target_bytes <= 0:
            message = "target_bytes must be positive"
            raise BenchmarkConfigurationError(message)


SMALL_DOCUMENT_PROFILE = DocumentSizeProfile("small", 200)
MEDIUM_DOCUMENT_PROFILE = DocumentSizeProfile("medium", 2_000)
LARGE_DOCUMENT_PROFILE = DocumentSizeProfile("large", 20_000)


def _deterministic_object_id(seed: int, index: int) -> ObjectId:
    digest = hashlib.sha256(f"{seed}:{index}".encode()).digest()
    return ObjectId(digest[:12])


def generate_seeded_documents(
    profile: DocumentSizeProfile, *, count: int, seed: int
) -> list[dict[str, object]]:
    if count <= 0:
        message = "count must be positive"
        raise BenchmarkConfigurationError(message)
    faker = Faker()
    faker.seed_instance(seed)
    documents: list[dict[str, object]] = []
    for index in range(count):
        document: dict[str, object] = {
            "_id": _deterministic_object_id(seed, index),
            "index": index,
            "name": faker.name(),
            "email": faker.email(),
            "created_at": faker.date_time(),
            "padding": "",
        }
        minimum_size = len(bson.encode(document))
        if minimum_size > profile.target_bytes:
            message = (
                f"{profile.name!r} profile's target_bytes "
                f"({profile.target_bytes}) is smaller than its base fields "
                f"({minimum_size} bytes)"
            )
            raise BenchmarkConfigurationError(message)
        padding_length = profile.target_bytes - minimum_size
        if padding_length:
            document["padding"] = faker.pystr(
                min_chars=padding_length, max_chars=padding_length
            )
        documents.append(document)
    return documents
