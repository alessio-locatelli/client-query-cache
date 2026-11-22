from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

NATIVE_CORE: Final = "client_query_cache._shared_index.LocalCacheCore"
_PACKAGE: Final = "client_query_cache/"
_REQUIRED_PAYLOAD: Final = frozenset(
    (f"{_PACKAGE}__init__.py", f"{_PACKAGE}_shared_index.abi3.so")
)


@dataclass(frozen=True, slots=True)
class Build:
    core: str
    wheel_sha256: str


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_installation(expected: Build, wheel: Path, package: Path) -> None:
    observed = digest(wheel)
    if observed != expected.wheel_sha256:
        message = f"{wheel} has SHA-256 {observed}; expected {expected.wheel_sha256}"
        raise ValueError(message)
    with zipfile.ZipFile(wheel) as archive:
        members = archive.namelist()
        missing = _REQUIRED_PAYLOAD.difference(members)
        if missing:
            message = (
                f"{wheel} is missing required package payload: "
                f"{', '.join(sorted(missing))}"
            )
            raise ValueError(message)
        for member in members:
            if not member.startswith(_PACKAGE) or member.endswith("/"):
                continue
            installed = package / member.removeprefix(_PACKAGE)
            if (
                not installed.is_file()
                or archive.read(member) != installed.read_bytes()
            ):
                message = f"installed {installed} differs from {wheel}"
                raise ValueError(message)


def verify_core(expected: Build, provenance: Mapping[str, str], prefix: Path) -> None:
    if provenance["core"] != expected.core:
        message = f"loaded {provenance['core']}; expected {expected.core}"
        raise ValueError(message)
    for field in ("library", "extension"):
        if not Path(provenance[field]).is_relative_to(prefix):
            message = f"{field} {provenance[field]} is outside {prefix}"
            raise ValueError(message)
