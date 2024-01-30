from typing import Any

from pymongo.collection import Collection
from pymongo.typings import _DocumentType


class CachedCollection(Collection):
    def find_one(
        self,
        filter: Any | None = None,
        *args: Any,
        projection: list[str] | dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> _DocumentType | None:
        try:
            return self._Collection__database._cache["findOne"][filter][projection]
        except KeyError:
            document = super().find_one(filter, *args, **kwargs)
            self._Collection__database._cache["findOne"][filter][projection]
        return document
