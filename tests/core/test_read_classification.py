from typing import Literal
from unittest.mock import Mock, create_autospec

import pytest
from pymongo import ReadPreference
from pymongo.errors import InvalidOperation

from client_query_cache._core.read_classification import request_bypass_reason
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
