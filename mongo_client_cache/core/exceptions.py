class NotCachedError(Exception):
    ...


class NotAPositiveNumberError(Exception):
    ...


class ReservedAttributeError(Exception):
    def __init__(self, attribute_name: str) -> None:
        super().__init__(
            f'"{attribute_name}" is a reserved attribute '
            + "and cannot be used as a database or collection name."
        )


class DocumentIdMissingError(Exception):
    def __init__(self) -> None:
        super().__init__(
            "The '_id' field is mandatory for the cache backend. "
            + "Excluding '_id' via projection is unsupported."
        )


class CannotEditImmutableCollectionError(Exception):
    def __init__(self, collection_name: str) -> None:
        super().__init__(
            f'You disabled watching changes on "{collection_name}" collection, so '
            + "the collection cannot be modified because the local cache will "
            + "become outdated. You must disable cache for this collection or enable "
            + "watching changes if you are going to change documents in the collection."
        )
