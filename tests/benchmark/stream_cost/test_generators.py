from __future__ import annotations

import bson
import pytest
from bson import ObjectId

from benchmarks.stream_cost.errors import BenchmarkConfigurationError
from benchmarks.stream_cost.generators import (
    LARGE_DOCUMENT_PROFILE,
    MEDIUM_DOCUMENT_PROFILE,
    SMALL_DOCUMENT_PROFILE,
    DocumentSizeProfile,
    generate_seeded_documents,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({"name": "", "target_bytes": 10}, id="empty_name"),
        pytest.param({"name": "small", "target_bytes": 0}, id="zero_target_bytes"),
        pytest.param({"name": "small", "target_bytes": -1}, id="negative_target_bytes"),
    ],
)
def test_document_size_profile_rejects_invalid_values(
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(BenchmarkConfigurationError):
        DocumentSizeProfile(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "profile", [SMALL_DOCUMENT_PROFILE, MEDIUM_DOCUMENT_PROFILE, LARGE_DOCUMENT_PROFILE]
)
def test_generate_seeded_documents_matches_the_target_size(
    profile: DocumentSizeProfile,
) -> None:
    documents = generate_seeded_documents(profile, count=5, seed=1)

    for document in documents:
        assert len(bson.encode(document)) == profile.target_bytes


def test_generate_seeded_documents_is_deterministic_for_the_same_seed() -> None:
    first = generate_seeded_documents(MEDIUM_DOCUMENT_PROFILE, count=10, seed=7)
    second = generate_seeded_documents(MEDIUM_DOCUMENT_PROFILE, count=10, seed=7)

    assert first == second


def test_generate_seeded_documents_differs_across_seeds() -> None:
    first = generate_seeded_documents(MEDIUM_DOCUMENT_PROFILE, count=10, seed=7)
    second = generate_seeded_documents(MEDIUM_DOCUMENT_PROFILE, count=10, seed=8)

    assert first != second


def test_generate_seeded_documents_assigns_deterministic_object_ids() -> None:
    first = generate_seeded_documents(MEDIUM_DOCUMENT_PROFILE, count=3, seed=11)
    second = generate_seeded_documents(MEDIUM_DOCUMENT_PROFILE, count=3, seed=11)

    assert [document["_id"] for document in first] == [
        document["_id"] for document in second
    ]
    assert all(isinstance(document["_id"], ObjectId) for document in first)
    assert len({document["_id"] for document in first}) == 3


def test_generate_seeded_documents_assigns_a_stable_increasing_index() -> None:
    documents = generate_seeded_documents(SMALL_DOCUMENT_PROFILE, count=4, seed=3)

    assert [document["index"] for document in documents] == [0, 1, 2, 3]


def test_generate_seeded_documents_rejects_a_non_positive_count() -> None:
    with pytest.raises(BenchmarkConfigurationError):
        generate_seeded_documents(SMALL_DOCUMENT_PROFILE, count=0, seed=1)


def test_generate_seeded_documents_allows_zero_padding_at_the_exact_minimum() -> None:
    baseline = generate_seeded_documents(LARGE_DOCUMENT_PROFILE, count=1, seed=5)[0]
    minimum_size = len(bson.encode({**baseline, "padding": ""}))
    exact_profile = DocumentSizeProfile("exact", minimum_size)

    documents = generate_seeded_documents(exact_profile, count=1, seed=5)

    assert not documents[0]["padding"]
    assert len(bson.encode(documents[0])) == minimum_size


def test_generate_seeded_documents_rejects_a_target_too_small_for_base_fields() -> None:
    tiny_profile = DocumentSizeProfile("tiny", target_bytes=1)

    with pytest.raises(BenchmarkConfigurationError):
        generate_seeded_documents(tiny_profile, count=1, seed=1)


def test_document_size_profiles_grow_from_small_to_large() -> None:
    assert (
        SMALL_DOCUMENT_PROFILE.target_bytes
        < MEDIUM_DOCUMENT_PROFILE.target_bytes
        < LARGE_DOCUMENT_PROFILE.target_bytes
    )
