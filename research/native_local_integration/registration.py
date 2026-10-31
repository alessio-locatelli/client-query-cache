"""Registered build identities and implementation expectations per acquisition."""

from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

PYTHON_CORE: Final = "client_query_cache._core.manager.CacheCore"
NATIVE_CORE: Final = "client_query_cache._shared_index.LocalCacheCore"
_PACKAGE: Final = "client_query_cache/"


@dataclass(frozen=True, slots=True)
class Build:
    core: str
    wheel_sha256: str


@dataclass(frozen=True, slots=True)
class Registration:
    node_hash: str
    builds: Mapping[str, Build]


REGISTRATIONS: Final[Mapping[str, Registration]] = {
    "pr-355": Registration(
        "595525f35b718ea67cd368334e97298943b07d1f36cdb91281833ebbed7e5bc8",  # pragma: allowlist secret  # noqa: E501 - Keep each registered digest as one literal.
        {
            "M": Build(
                PYTHON_CORE,
                "85fa6e72c5526006fb051e7f96efe864b80e4d823a4716d1a700da70326128b7",  # pragma: allowlist secret  # noqa: E501 - Keep each registered digest as one literal.
            ),
            "F": Build(
                NATIVE_CORE,
                "75cdc05312c975613ae2883b4ae61386219378dbe6072e194558a5dc6b25c6a0",  # pragma: allowlist secret  # noqa: E501 - Keep each registered digest as one literal.
            ),
        },
    ),
    "native-internals": Registration(
        "0932ab7d5cd03042c753506af599a7045efe8b9387769b0cec019643f8270ec7",  # pragma: allowlist secret  # noqa: E501 - Keep each registered digest as one literal.
        {
            "M": Build(
                NATIVE_CORE,
                "d133597a0fc6119d2dda266abc3ab8cfc6bb508e2f53585cb8487e300d87b2b8",  # pragma: allowlist secret  # noqa: E501 - Keep each registered digest as one literal.
            ),
            "capture": Build(
                NATIVE_CORE,
                "449554b295516791183f57d7555c085f26648dde1a40fceac7d9cdd7e46ebf61",  # pragma: allowlist secret  # noqa: E501 - Keep each registered digest as one literal.
            ),
            "preparation": Build(
                NATIVE_CORE,
                "db51c069f9db1ca678b27ad6653a9a619d7345687c9656c7dcf78faab4613511",  # pragma: allowlist secret  # noqa: E501 - Keep each registered digest as one literal.
            ),
        },
    ),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(registration: str, label: str) -> Build:
    try:
        return REGISTRATIONS[registration].builds[label]
    except KeyError:
        message = f"{label!r} is not a registered {registration!r} build"
        raise ValueError(message) from None


def verify_installation(expected: Build, wheel: Path, package: Path) -> None:
    observed = digest(wheel)
    if observed != expected.wheel_sha256:
        message = f"{wheel} has SHA-256 {observed}; expected {expected.wheel_sha256}"
        raise ValueError(message)
    with zipfile.ZipFile(wheel) as archive:
        for member in archive.namelist():
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
