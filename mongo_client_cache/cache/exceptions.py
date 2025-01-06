from __future__ import annotations

from typing import Any


class CannotEditImmutableCollectionError(Exception):
    def __init__(self, collection_name: str) -> None:
        super().__init__(
            f'You disabled watching changes on "{collection_name}" collection, so '
            + "the collection cannot be modified because the local cache will "
            + "become outdated. You must disable cache for this collection or enable "
            + "watching changes if you are going to change documents in the collection."
        )


class UnexpectedChangeOperationTypeError(Exception): ...


class WaitingForChangeStreamError(Exception):
    def __init__(
        self, max_change_stream_await_time_s: float, info: dict[str, Any]
    ) -> None:
        super().__init__(
            f"{max_change_stream_await_time_s} seconds timeout "
            + f"exceeded while waiting for a change stream. {info=}"
        )
