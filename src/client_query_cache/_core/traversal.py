from __future__ import annotations


def declared_attribute_names(pymongo_type: type) -> frozenset[str]:
    return frozenset(dir(pymongo_type))


def ensure_subcollection_name(
    view: object, name: str, declared_names: frozenset[str]
) -> None:
    if name.startswith("_"):
        message = f"{type(view).__name__!r} object has no attribute {name!r}"
        raise AttributeError(message)
    if name in declared_names:
        message = (
            f"{type(view).__name__!r} object has no attribute {name!r}; call "
            f"{name!r} on the PyMongo object or on `.raw`, or use [{name!r}] "
            f"for a collection with that name"
        )
        raise AttributeError(message)
