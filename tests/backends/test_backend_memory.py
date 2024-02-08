from mongo_client_cache.backends.memory import MemoryBackend


class TestMemoryBackend:
    def memory_backend(self) -> MemoryBackend:
        return MemoryBackend()

    def test_get_one(self, memory_backend: MemoryBackend) -> None: ...

    def test_set_one(self, memory_backend: MemoryBackend) -> None: ...

    def test_get_many(self, memory_backend: MemoryBackend) -> None: ...

    def test_set_many(self, memory_backend: MemoryBackend) -> None: ...
