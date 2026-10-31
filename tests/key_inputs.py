from __future__ import annotations

from collections import UserDict, UserList
from typing import TYPE_CHECKING

from bson.decimal128 import Decimal128
from bson.int64 import Int64
from bson.son import SON
from hypothesis import strategies as st

if TYPE_CHECKING:
    from collections.abc import Callable


class Opaque:
    __slots__ = ("value",)

    def __init__(self, value: object) -> None:
        self.value = value

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Opaque) and self.value == other.value

    def __hash__(self) -> int:
        return hash(self.value)


_TEXT = st.text(max_size=6) | st.sampled_from(
    ["it's", 'say "hi"', "back\\slash", "tab\tline\n", "\ud800", "é", "", " "]
)
_LEAVES = (
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats()
    | _TEXT
    | st.binary(max_size=4)
    | st.integers(min_value=-(2**63), max_value=2**63 - 1).map(Int64)
    | st.sampled_from(["1", "1.0", "-0", "NaN", "Infinity"]).map(Decimal128)
    | _TEXT.map(Opaque)
)


def key_inputs(*, string_keys: bool = False) -> st.SearchStrategy[object]:
    keys = _TEXT if string_keys else _TEXT | st.integers() | st.booleans()
    return st.recursive(
        _LEAVES,
        lambda children: (
            st.lists(children, max_size=4)
            | st.lists(children, max_size=4).map(tuple)
            | st.lists(children, max_size=4).map(UserList)
            | st.dictionaries(keys, children, max_size=4)
            | st.dictionaries(_TEXT, children, max_size=4).map(SON)
            | st.dictionaries(_TEXT, children, max_size=4).map(UserDict)
        ),
        max_leaves=12,
    )


def outcome(function: Callable[[object], object], value: object) -> tuple[object, ...]:
    try:
        return ("result", function(value))
    except Exception as error:  # noqa: BLE001 - Compare every failure between implementations.
        return ("error", type(error), str(error))


def strictly_equal(first: object, second: object) -> bool:
    if type(first) is tuple and type(second) is tuple:
        return len(first) == len(second) and all(
            map(strictly_equal, first, second, strict=True)
        )
    return type(first) is type(second) and (
        first is second or first == second or (first != first and second != second)  # noqa: PLR0124 (deliberate self-inequality check for NaN-like values)
    )


def same_outcome(first: tuple[object, ...], second: tuple[object, ...]) -> bool:
    if first[0] == second[0] == "result":
        return strictly_equal(first[1], second[1])
    return first == second
