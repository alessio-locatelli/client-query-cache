from typing import final

@final
class FloorIndex:
    def __init__(
        self,
        slots: int,
        arena_bytes: int,
        databases: int,
        namespaces: int,
        ring_tokens: int,
        incarnation: int,
        expiry_ns: int,
    ) -> None: ...
    def publish(
        self,
        namespace: int,
        epoch: int,
        identity: bytes,
        shape: bytes,
        payload: bytes,
        token: int,
    ) -> bool: ...
    def set_available(self, database: int, available: bool) -> None: ...
    def set_progress(self, database: int, monotonic_ns: int) -> None: ...
    def set_epoch(self, namespace: int, epoch: int) -> None: ...
    def drain(self) -> int: ...
    def dropped(self) -> int: ...
    def reader(self) -> FloorReader: ...
    def serve(self, path: str) -> EchoOwner: ...

@final
class FloorReader:
    def lookup(
        self, database: int, namespace: int, epoch: int, identity: bytes, shape: bytes
    ) -> bytes | None: ...
    def detach(self) -> None: ...

@final
class EchoOwner:
    def close(self) -> None: ...
