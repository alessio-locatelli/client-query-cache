"""Identify already-imported library artifacts in an acquisition process."""

from __future__ import annotations

import sys


def implementation(core: object | None) -> dict[str, str]:
    paths: dict[str, str] = {}
    for field, module in (
        ("library", "client_query_cache"),
        ("extension", "client_query_cache._shared_index"),
    ):
        try:
            imported = sys.modules[module]
        except KeyError:
            paths[field] = "unimported"
        else:
            paths[field] = str(imported.__file__)
    return {
        "core": "direct"
        if core is None
        else f"{type(core).__module__}.{type(core).__qualname__}",
        **paths,
        "interpreter": sys.executable,
        "prefix": sys.prefix,
    }
