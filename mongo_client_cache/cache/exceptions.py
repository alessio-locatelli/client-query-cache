from __future__ import annotations


class CannotEditImmutableCollectionError(Exception):
    def __init__(self, collection_name: str) -> None:
        super().__init__(
            f'You disabled watching changes on "{collection_name}" collection, so '
            + "the collection cannot be modified because the local cache will "
            + "become outdated. You must disable cache for this collection or enable "
            + "watching changes if you are going to change documents in the collection."
        )


class UnexpectedChangeOperationTypeError(Exception): ...
