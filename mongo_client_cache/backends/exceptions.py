class NotCachedError(Exception): ...


class NotAPositiveNumberError(Exception): ...


class ReservedAttributeError(Exception):
    def __init__(self, attribute_name: str) -> None:
        super().__init__(
            f'"{attribute_name}" is a reserved attribute '
            + "and cannot be used as a database or collection name."
        )
