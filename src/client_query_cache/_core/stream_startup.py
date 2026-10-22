from __future__ import annotations

from typing import TYPE_CHECKING

from pymongo.errors import OperationFailure

from client_query_cache._types import NonEmptyStr

if TYPE_CHECKING:
    from pymongo.errors import PyMongoError

_STANDALONE_CHANGE_STREAM_ERROR = 40573


def stream_startup_failure_message(
    database_name: NonEmptyStr, error: PyMongoError
) -> NonEmptyStr:
    message = f"failed to open change stream for database {database_name!r}"
    if (
        isinstance(error, OperationFailure)
        and error.code == _STANDALONE_CHANGE_STREAM_ERROR
    ):
        message += (
            "; caching requires a MongoDB replica set or sharded cluster. "
            "For local setup, see "
            "https://alessio-locatelli.github.io/client-query-cache/"
            "getting-started/installation/#local-mongodb"
        )
    return message
