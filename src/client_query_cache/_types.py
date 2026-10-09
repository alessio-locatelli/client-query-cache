from __future__ import annotations

from typing import Annotated

from annotated_types import Ge, Gt, Interval, MinLen

from client_query_cache._core.stream_options import MAX_AWAIT_TIME_MS

type PositiveInt = Annotated[int, Gt(0)]
type NonNegativeInt = Annotated[int, Ge(0)]
type MaxAwaitTimeMs = Annotated[int, Interval(ge=1, le=MAX_AWAIT_TIME_MS)]
type PositiveFloat = Annotated[float, Gt(0)]
type NonEmptyStr = Annotated[str, MinLen(1)]
