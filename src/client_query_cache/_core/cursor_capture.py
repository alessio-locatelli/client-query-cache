from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

from client_query_cache._core.codec import encode_value
from client_query_cache._core.errors import CacheClosedError
from client_query_cache._shared_index import EncodedArray

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bson.codec_options import CodecOptions

    from client_query_cache._core.contracts import LocalCacheCore, NamespaceCaptureView
    from client_query_cache._core.entries import AdmissionOutcome
    from client_query_cache._core.find_reads import FindSource
    from client_query_cache._types import NonNegativeInt


class CursorCapture:
    """Own immutable document snapshots until consumption completes."""

    __slots__ = (
        "_active",
        "_capture",
        "_codec_options",
        "_core",
        "_discriminator",
        "_documents",
        "_find_source",
        "_release_capture",
    )

    def __init__(
        self,
        core: LocalCacheCore,
        capture: NamespaceCaptureView,
        discriminator: object,
        codec_options: CodecOptions[Mapping[str, Any]],
        *,
        find_source: FindSource | None = None,
        release_capture: bool = False,
    ) -> None:
        self._release_capture = release_capture
        self._core = core
        self._capture = capture
        self._discriminator = discriminator
        self._codec_options = codec_options
        self._find_source = find_source
        # An empty result is cacheable.
        self._documents = EncodedArray(min(core.max_entry_bytes, sys.maxsize))
        self._active = True

    @property
    def retained_bytes(self) -> NonNegativeInt:
        return self._documents.retained_bytes

    def append(self, document: Mapping[str, Any]) -> None:
        if not self._active:
            return
        try:
            # Embedded encoding preserves field order; top-level encoding promotes _id.
            retained = self._documents.append(
                encode_value(document, self._codec_options)
            )
        except Exception:  # noqa: BLE001 - Application BSON encoders can raise arbitrary errors.
            self.abandon()
            return
        if not retained:
            if self._core.enable_telemetry:
                self._core.record_oversized_bypass()
            self.abandon()

    def abandon(self) -> None:
        self._active = False
        self._documents.clear()
        if self._release_capture:
            self._capture.release()

    def finish(self) -> AdmissionOutcome | None:
        if not self._active:
            return None
        self._active = False
        try:
            return self._core.admit_namespace_encoded(
                self._capture,
                self._discriminator,
                self._documents.finish(),
                find_source=self._find_source,
            )
        except CacheClosedError:
            # The cursor owns its native resources independently of the manager.
            return None
        finally:
            if self._release_capture:
                self._capture.release()
            self._documents.clear()
