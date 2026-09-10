from __future__ import annotations


class CacheError(Exception):
    pass


class CacheConfigurationError(CacheError, ValueError):
    pass


class UnsupportedCacheRequestError(CacheError, TypeError):
    pass


class CacheClosedError(CacheError):
    pass
