from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bson.raw_bson import DEFAULT_RAW_BSON_OPTIONS, RawBSONDocument

from client_query_cache._core.codec import encode_value
from client_query_cache._core.errors import CacheClosedError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bson.codec_options import CodecOptions

    from client_query_cache._core.entries import AdmissionOutcome
    from client_query_cache._core.manager import CacheCore, NamespaceCapture


class CursorCapture:
    """Own immutable document snapshots until consumption completes."""

    __slots__ = (
        "_active",
        "_capture",
        "_codec_options",
        "_core",
        "_discriminator",
        "_documents",
        "_max_entry_bytes",
        "retained_bytes",
    )

    def __init__(
        self,
        core: CacheCore,
        capture: NamespaceCapture,
        discriminator: object,
        codec_options: CodecOptions[Mapping[str, Any]],
    ) -> None:
        self._core = core
        self._capture = capture
        self._discriminator = discriminator
        self._codec_options = codec_options
        self._max_entry_bytes = core.snapshot().max_entry_bytes
        self._documents: list[RawBSONDocument] = []  # An empty result is cacheable.
        self.retained_bytes = 0  # Empty and abandoned captures retain no payload.
        self._active = True

    def append(self, document: Mapping[str, Any]) -> None:
        if not self._active:
            return
        try:
            encoded = encode_value(document, self._codec_options)
        except Exception:  # noqa: BLE001 - Application BSON encoders can raise arbitrary errors.
            self.abandon()
            return
        if self.retained_bytes + len(encoded) > self._max_entry_bytes:
            self._core.record_oversized_bypass()
            self.abandon()
            return
        # Access the envelope without replaying application codec transformations.
        envelope = RawBSONDocument(encoded, DEFAULT_RAW_BSON_OPTIONS)
        self._documents.append(envelope["v"])
        self.retained_bytes += len(encoded)

    def abandon(self) -> None:
        self._active = False
        self._documents.clear()
        self.retained_bytes = 0

    def finish(self) -> AdmissionOutcome | None:
        if not self._active:
            return None
        self._active = False
        try:
            return self._core.admit_namespace(
                self._capture,
                self._discriminator,
                self._documents,
                codec_options=self._codec_options,
            )
        except CacheClosedError:
            # The cursor owns its native resources independently of the manager.
            return None
        finally:
            self._documents.clear()
            self.retained_bytes = 0
