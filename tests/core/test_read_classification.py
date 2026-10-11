from typing import Literal
from unittest.mock import Mock, create_autospec

import pytest
from pymongo import ReadPreference
from pymongo.errors import InvalidOperation

from client_query_cache._core.canonical import canonicalize
from client_query_cache._core.read_classification import (
    prepare_pipeline_key,
    prepare_query_key,
    request_bypass_reason,
)
from client_query_cache._core.snapshots import BypassReason

pytestmark = pytest.mark.unit


@pytest.fixture
def resolver() -> Mock:
    callback: Mock = create_autospec(lambda: None)
    return callback


@pytest.mark.parametrize(
    ("explicit", "capability", "expected"),
    [
        (False, "unbound", None),
        (False, "bound", BypassReason.SESSION),
        (False, "invalid", BypassReason.SESSION),
        (False, "signature", BypassReason.SESSION),
        (False, "implementation", BypassReason.SESSION),
        (False, "missing", BypassReason.SESSION),
        (False, "noncallable", BypassReason.SESSION),
        (True, "invalid", BypassReason.SESSION),
    ],
    ids=(
        "unbound",
        "bound",
        "foreign-context",
        "changed-signature",
        "changed-implementation",
        "missing-capability",
        "changed-capability",
        "explicit-precedence",
    ),
)
def test_effective_session_selects_native_execution(
    resolver: Mock,
    explicit: bool,
    capability: Literal[
        "unbound",
        "bound",
        "invalid",
        "signature",
        "implementation",
        "missing",
        "noncallable",
    ],
    expected: BypassReason | None,
) -> None:
    resolver.return_value = None if capability == "unbound" else "bound-session"
    if capability == "invalid":
        resolver.side_effect = InvalidOperation("foreign bound session")
    elif capability == "signature":
        resolver.side_effect = TypeError("changed private resolver signature")
    elif capability == "implementation":
        resolver.side_effect = AttributeError("changed private resolver implementation")
    callback: object = resolver
    if capability == "missing":
        callback = None
    elif capability == "noncallable":
        callback = "changed private attribute"
    assert (
        request_bypass_reason(
            "explicit-session" if explicit else None,
            ReadPreference.PRIMARY,
            None,
            {},
            bound_session=callback,
        )
        == expected
    )
    if explicit or not callable(callback):
        resolver.assert_not_called()
    else:
        resolver.assert_called_once_with()


@pytest.mark.parametrize("pipeline", [False, True], ids=["query", "pipeline"])
@pytest.mark.parametrize(
    ("raw_key", "expected_reason"),
    [
        pytest.param(None, None, id="none-key"),
        pytest.param({"v": [1, True, "value"]}, None, id="safe-tree"),
        pytest.param(float("nan"), BypassReason.UNCANONICALIZABLE_KEY, id="nan"),
        pytest.param(set(), BypassReason.UNCANONICALIZABLE_KEY, id="unhashable"),
    ],
)
def test_prepare_read_key(
    pipeline: bool, raw_key: object, expected_reason: BypassReason | None
) -> None:
    if pipeline:
        key, reason = prepare_pipeline_key([{"$match": {"v": 1}}], raw_key)
    else:
        key, reason = prepare_query_key({"v": 1}, {"v": 1}, raw_key)
    assert reason == expected_reason
    if reason is None:
        assert key == canonicalize(raw_key)
    else:
        assert key is None


@pytest.mark.parametrize("pipeline", [False, True], ids=["query", "pipeline"])
def test_prepared_read_key_retains_canonical_identity(pipeline: bool) -> None:
    canonical_key = canonicalize({"v": [1, True]})
    if pipeline:
        key, reason = prepare_pipeline_key([], canonical_key)
    else:
        key, reason = prepare_query_key({}, None, canonical_key)
    assert reason is None
    assert key is canonical_key


@pytest.mark.parametrize(
    ("filter_query", "projection", "expected_reason"),
    [
        pytest.param({"$where": "true"}, None, BypassReason.UNSAFE_FILTER, id="filter"),
        pytest.param(
            {},
            {"v": {"$meta": "textScore"}},
            BypassReason.UNSAFE_PROJECTION,
            id="projection",
        ),
        pytest.param(
            {"$where": "true"},
            {"v": {"$meta": "textScore"}},
            BypassReason.UNSAFE_FILTER,
            id="filter-precedes-projection",
        ),
    ],
)
def test_unsafe_query_skips_key_preparation(
    monkeypatch: pytest.MonkeyPatch,
    filter_query: dict[str, object],
    projection: dict[str, object] | None,
    expected_reason: BypassReason,
) -> None:
    spy = Mock(side_effect=AssertionError("unsafe input must skip canonicalization"))
    monkeypatch.setattr(
        "client_query_cache._core.read_classification.canonicalize", spy
    )
    assert prepare_query_key(filter_query, projection, float("nan")) == (
        None,
        expected_reason,
    )
    spy.assert_not_called()


def test_unsafe_pipeline_skips_key_preparation(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = Mock(side_effect=AssertionError("unsafe input must skip canonicalization"))
    monkeypatch.setattr(
        "client_query_cache._core.read_classification.canonicalize", spy
    )
    assert prepare_pipeline_key([{"$sample": {"size": 1}}], float("nan")) == (
        None,
        BypassReason.UNSAFE_PIPELINE,
    )
    spy.assert_not_called()
