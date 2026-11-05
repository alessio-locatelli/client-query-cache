from __future__ import annotations

import os
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

from client_query_cache._types import NonNegativeInt

if TYPE_CHECKING:
    from collections.abc import Collection

type FileIdentity = tuple[NonNegativeInt, NonNegativeInt]


def file_identity(descriptor: NonNegativeInt) -> FileIdentity:
    status = os.fstat(descriptor)
    return status.st_dev, status.st_ino


def references(files: Collection[FileIdentity]) -> Counter[FileIdentity]:
    counts: Counter[FileIdentity] = Counter()
    for entry in Path("/proc/self/fd").iterdir():
        try:
            status = entry.stat()
        except FileNotFoundError:  # pragma: lax no cover (closed by another thread)
            continue
        identity = (status.st_dev, status.st_ino)
        if identity in files:
            counts[identity] += 1
    return counts
