from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from client_query_cache._core.canonical import canonicalize
from client_query_cache._core.codec import encode_value
from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.find_reads import find_read_shape
from client_query_cache._core.keys import IdentityCacheKey, NamespaceCacheKey
from client_query_cache._core.manager import CacheCore, CacheCoreConfig
from client_query_cache._core.order_sensitive_keys import order_sensitive_key
from tests.core.conftest import patch_conditional_put_hook

if TYPE_CHECKING:
    from collections.abc import Callable

    from faker import Faker

    from client_query_cache._core.canonical import Canonical
    from client_query_cache._core.entries import CacheEntry
    from client_query_cache._core.keys import CacheKey, NamespaceId
    from client_query_cache._types import NonNegativeInt

pytestmark = pytest.mark.unit

SHAPE = "full"
DISCRIMINATOR = ("find", "shape")
LARGE_CHARACTERS = 600
BUDGET = CacheCoreConfig(shared_budget_bytes=1_000, max_entry_bytes=700)

type Event = tuple[str, object]


@dataclass(slots=True)
class RecordingObserver:
    core: CacheCore | None = None
    events: list[Event] = field(default_factory=list)
    locked: list[bool] = field(default_factory=list)

    def _record(self, kind: str, subject: object, *, locked: bool) -> None:
        self.events.append((kind, subject))
        self.locked.append(locked)

    def _namespace_locked(self, namespace: NamespaceId) -> bool:
        assert self.core is not None
        return self.core._namespaces[namespace].lock.locked()

    def admitted(self, key: CacheKey, entry: CacheEntry) -> None:
        self._record(
            "admitted",
            (key, entry.value),
            locked=self._namespace_locked(key.namespace),
        )

    def removed(self, key: CacheKey, entry: CacheEntry) -> None:
        assert self.core is not None
        self._record(
            "removed", (key, entry.value), locked=self.core._lru._lock.locked()
        )

    def identity_written(self, namespace: NamespaceId, identity: Canonical) -> None:
        self._record(
            "identity_written",
            (namespace, identity),
            locked=self._namespace_locked(namespace),
        )

    def epoch_changed(self, namespace: NamespaceId, epoch: NonNegativeInt) -> None:
        self._record(
            "epoch_changed",
            (namespace, epoch),
            locked=self._namespace_locked(namespace),
        )

    def availability_changed(self, database: str, *, available: bool) -> None:
        assert self.core is not None
        self._record(
            "availability_changed",
            (database, available),
            locked=self.core._availability_lock.locked(),
        )


@dataclass(frozen=True, slots=True)
class Scenario:
    core: CacheCore
    namespace: NamespaceId
    faker: Faker
    observer: RecordingObserver
    monkeypatch: pytest.MonkeyPatch

    def document(self, characters: NonNegativeInt = 0) -> bytes:
        text = self.faker.pystr(min_chars=characters, max_chars=characters)
        return encode_value({"name": self.faker.name(), "text": text})

    def key(self, identity: str) -> IdentityCacheKey:
        return IdentityCacheKey(
            self.namespace,
            canonicalize(order_sensitive_key(identity)),
            canonicalize(SHAPE),
        )

    def admit(self, identity: str, encoded: bytes) -> IdentityCacheKey:
        capture = self.core.begin_identity_admission(self.namespace, identity)
        outcome = self.core.admit_identity_encoded(capture, SHAPE, encoded)
        assert outcome is AdmissionOutcome.ADMITTED
        return self.key(identity)


def _committed_admission(scenario: Scenario) -> list[Event]:
    encoded = scenario.document()
    return [("admitted", (scenario.admit("doc-1", encoded), encoded))]


def _rolled_back_admission(scenario: Scenario) -> list[Event]:
    capture = scenario.core.begin_identity_admission(scenario.namespace, "doc-1")
    encoded = scenario.document()

    def write_after_insert(_key: CacheKey, _entry: CacheEntry) -> None:
        scenario.core.record_write(scenario.namespace, "doc-1")

    patch_conditional_put_hook(scenario.monkeypatch, scenario.core, write_after_insert)
    outcome = scenario.core.admit_identity_encoded(capture, SHAPE, encoded)
    assert outcome is AdmissionOutcome.DECLINED_STALE
    key = scenario.key("doc-1")
    return [
        ("identity_written", (scenario.namespace, key.identity)),
        ("removed", (key, encoded)),
    ]


def _displacement(scenario: Scenario) -> list[Event]:
    previous = scenario.document()
    scenario.admit("doc-1", previous)
    scenario.core.record_write(scenario.namespace, "doc-1")
    scenario.observer.events.clear()
    current = scenario.document()
    key = scenario.admit("doc-1", current)
    return [("removed", (key, previous)), ("admitted", (key, current))]


def _eviction(scenario: Scenario) -> list[Event]:
    oldest = scenario.document(LARGE_CHARACTERS)
    oldest_key = scenario.admit("doc-1", oldest)
    scenario.observer.events.clear()
    newest = scenario.document(LARGE_CHARACTERS)
    newest_key = scenario.admit("doc-2", newest)
    return [("removed", (oldest_key, oldest)), ("admitted", (newest_key, newest))]


def _remove_exact(scenario: Scenario) -> list[Event]:
    capture = scenario.core.capture_namespace_generation(scenario.namespace)
    encoded = scenario.document()
    outcome = scenario.core.admit_namespace_encoded(capture, DISCRIMINATOR, encoded)
    assert outcome is AdmissionOutcome.ADMITTED
    scenario.observer.events.clear()
    scenario.core.discard_namespace_entry(
        scenario.namespace, DISCRIMINATOR, capture.generation
    )
    key = NamespaceCacheKey(scenario.namespace, canonicalize(DISCRIMINATOR))
    return [("removed", (key, encoded))]


def _clear_all(scenario: Scenario) -> list[Event]:
    encoded = scenario.document()
    key = scenario.admit("doc-1", encoded)
    scenario.observer.events.clear()
    scenario.core.close()
    return [("removed", (key, encoded))]


def _identity_write(scenario: Scenario) -> list[Event]:
    key = scenario.admit("doc-1", scenario.document())
    scenario.observer.events.clear()
    scenario.core.record_write(scenario.namespace, "doc-1")
    return [("identity_written", (scenario.namespace, key.identity))]


def _namespace_reset(scenario: Scenario) -> list[Event]:
    encoded = scenario.document()
    key = scenario.admit("doc-1", encoded)
    scenario.observer.events.clear()
    scenario.core.clear_namespace(scenario.namespace)
    return [("epoch_changed", (scenario.namespace, 1)), ("removed", (key, encoded))]


def _untracked_identity_write(scenario: Scenario) -> list[Event]:
    identity = scenario.faker.pyint()
    scenario.core.record_write(scenario.namespace, identity)
    return [("identity_written", (scenario.namespace, canonicalize(identity)))]


def _availability_change(scenario: Scenario) -> list[Event]:
    scenario.core.set_database_available(scenario.namespace.database, available=False)
    return [("availability_changed", (scenario.namespace.database, False))]


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(_committed_admission, id="committed-admission"),
        pytest.param(_rolled_back_admission, id="rolled-back-admission"),
        pytest.param(_displacement, id="displacement"),
        pytest.param(_eviction, id="eviction"),
        pytest.param(_remove_exact, id="remove-exact"),
        pytest.param(_clear_all, id="clear-all"),
        pytest.param(_identity_write, id="identity-write"),
        pytest.param(_untracked_identity_write, id="untracked-identity-write"),
        pytest.param(_namespace_reset, id="namespace-reset"),
        pytest.param(_availability_change, id="availability-change"),
    ],
)
def test_observer_sees_each_mutation_inside_its_lock_section(
    namespace: NamespaceId,
    faker: Faker,
    monkeypatch: pytest.MonkeyPatch,
    mutate: Callable[[Scenario], list[Event]],
) -> None:
    observer = RecordingObserver()
    core = CacheCore(BUDGET, observer=observer)
    observer.core = core
    expected = mutate(Scenario(core, namespace, faker, observer, monkeypatch))
    assert observer.events == expected
    assert all(observer.locked)


@dataclass(eq=False, slots=True)
class Stored:
    encoded: bytes


@dataclass(slots=True)
class RecordingPayloads:
    intact: bool
    stored: list[Stored] = field(default_factory=list)
    released: list[object] = field(default_factory=list)

    def store(self, encoded: bytes) -> object:
        stored = Stored(encoded)
        self.stored.append(stored)
        return stored

    def release(self, stored: object) -> None:
        self.released.append(stored)

    def snapshot(self, stored: object) -> bytes | None:
        assert isinstance(stored, Stored)
        return stored.encoded if self.intact else None


def _identity_read(core: CacheCore, namespace: NamespaceId, encoded: bytes) -> object:
    capture = core.begin_identity_admission(namespace, "doc-1")
    core.admit_identity_encoded(capture, SHAPE, encoded)
    return core.lookup_identity_encoded(namespace, "doc-1", SHAPE)


def _find_read(core: CacheCore, namespace: NamespaceId, encoded: bytes) -> object:
    shape = find_read_shape({}, None, {"_id": 1}, 0, 2, collation=None, codec="codec")
    capture = core.capture_namespace_generation(namespace)
    core.admit_namespace_encoded(
        capture, shape.discriminator, encoded, find_source=shape.source
    )
    return core.lookup_find_encoded(namespace, shape)


def _namespace_read(core: CacheCore, namespace: NamespaceId, encoded: bytes) -> object:
    capture = core.capture_namespace_generation(namespace)
    core.admit_namespace_encoded(capture, DISCRIMINATOR, encoded)
    value = core.lookup_namespace_encoded(namespace, DISCRIMINATOR)
    return value if isinstance(value, bytes) else None


@pytest.mark.parametrize(
    "read",
    [
        pytest.param(_identity_read, id="identity"),
        pytest.param(_find_read, id="find"),
        pytest.param(_namespace_read, id="namespace"),
    ],
)
@pytest.mark.parametrize(
    "intact", [pytest.param(True, id="intact"), pytest.param(False, id="removed")]
)
def test_encoded_hits_return_the_payload_snapshot(
    namespace: NamespaceId,
    faker: Faker,
    read: Callable[[CacheCore, NamespaceId, bytes], object],
    *,
    intact: bool,
) -> None:
    core = CacheCore(payloads=RecordingPayloads(intact=intact))
    encoded = encode_value({"name": faker.name()})
    value = read(core, namespace, encoded)
    snapshot = core.snapshot()
    assert value == (encoded if intact else None)
    assert (snapshot.hits, snapshot.misses) == ((1, 0) if intact else (0, 1))


def test_every_stored_payload_is_released_once_after_leaving_the_cache(
    namespace: NamespaceId, faker: Faker
) -> None:
    payloads = RecordingPayloads(intact=True)
    core = CacheCore(BUDGET, payloads=payloads)
    duplicate = core.begin_identity_admission(namespace, "doc-1")
    first = core.begin_identity_admission(namespace, "doc-1")
    for capture in (first, duplicate):
        core.admit_identity_encoded(capture, SHAPE, encode_value({"n": faker.name()}))
    core.record_write(namespace, "doc-1")
    for identity in ("doc-1", "doc-2", "doc-3"):
        capture = core.begin_identity_admission(namespace, identity)
        text = faker.pystr(min_chars=LARGE_CHARACTERS, max_chars=LARGE_CHARACTERS)
        core.admit_identity_encoded(capture, SHAPE, encode_value({"text": text}))
    core.close()
    assert len(payloads.stored) == 5
    assert sorted(map(id, payloads.released)) == sorted(map(id, payloads.stored))
