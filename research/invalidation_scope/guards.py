"""Experimental generation guards for the fixed invalidation-study queries."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from unittest.mock import patch

from client_query_cache._core import manager as core_module
from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.namespace import NamespaceState
from client_query_cache._core.stream_events import route_change_event
from client_query_cache._types import BsonDict, NonNegativeFloat, NonNegativeInt
from client_query_cache.synchronous import streams as stream_module
from client_query_cache.synchronous.collection import CachedCollection
from research.invalidation_scope.stream_projection import Mode, pipeline

if TYPE_CHECKING:
    from collections.abc import Mapping
    from contextlib import ExitStack

    from client_query_cache._core.locking import NamespaceLock
    from client_query_cache._core.manager import CacheCore
    from client_query_cache.synchronous.database import CachedDatabase

Policy = Literal["current", "insert", "fields"]
ReadKind = Literal["feed", "count", "own", "by_id"]
POLICY_PROJECTIONS: dict[Policy, Mode] = {
    "current": "routing",
    "insert": "scalar",
    "fields": "names",
}
LOCAL_GENERATION_BITS = 64
LOCAL_GENERATION_MASK = (1 << LOCAL_GENERATION_BITS) - 1


@dataclass(slots=True)
class Fence:
    generation: NonNegativeInt = 0


class PartitionState(NamespaceState):
    __slots__ = ("_fence", "_local_generation")

    def __init__(
        self, namespace: NamespaceId, lock: NamespaceLock, fence: Fence
    ) -> None:
        self._fence = fence
        self._local_generation = 0
        super().__init__(namespace, lock)

    @property
    def generation(self) -> NonNegativeInt:
        return (
            self._fence.generation << LOCAL_GENERATION_BITS
        ) | self._local_generation

    @generation.setter
    def generation(self, value: NonNegativeInt) -> None:
        self._local_generation = value & LOCAL_GENERATION_MASK


class GuardedCollection(CachedCollection[BsonDict]):
    __slots__ = ()

    def __init__(
        self,
        database: CachedDatabase[BsonDict],
        original: CachedCollection[BsonDict],
        namespace: NamespaceId,
    ) -> None:
        super().__init__(database, original.raw)
        self._namespace_id = namespace


class GuardRouter:
    __slots__ = (
        "applied",
        "condition",
        "dependency_namespaces",
        "fallbacks",
        "fences",
        "partitions",
        "policy",
        "route_cpu_ns",
        "states",
    )

    def __init__(self, policy: Policy) -> None:
        self.policy = policy
        self.fences: dict[NamespaceId, Fence] = {}
        self.fallbacks: dict[NamespaceId, Fence] = {}
        self.partitions: dict[NamespaceId, dict[NonNegativeInt, NamespaceId]] = {}
        self.dependency_namespaces: dict[NamespaceId, NamespaceId] = {}
        self.states: dict[NamespaceId, NamespaceState] = {}
        self.condition = threading.Condition()
        self.applied: list[NonNegativeFloat] = []
        self.route_cpu_ns = 0

    def collection(
        self,
        original: CachedCollection[BsonDict],
        kind: ReadKind,
        author: NonNegativeInt,
    ) -> CachedCollection[BsonDict]:
        physical = NamespaceId(original.database.name, original.name)
        if self.policy == "insert" and kind in {"feed", "count"}:
            try:
                by_author = self.partitions[physical]
            except KeyError:
                by_author = self.partitions[physical] = {}
                self.fallbacks[physical] = Fence()
            try:
                namespace = by_author[author]
            except KeyError:
                namespace = by_author[author] = NamespaceId(
                    physical.database, f"{physical.collection}#author:{author}"
                )
                self.fences[namespace] = self.fallbacks[physical]
        elif self.policy == "fields" and kind == "count":
            namespace = self.dependency_namespaces.setdefault(
                physical,
                NamespaceId(physical.database, f"{physical.collection}#counts"),
            )
        else:
            return original
        return GuardedCollection(original.database, original, namespace)

    def state(self, namespace: NamespaceId, lock: NamespaceLock) -> NamespaceState:
        try:
            fence = self.fences[namespace]
        except KeyError:
            state = NamespaceState(namespace, lock)
        else:
            state = PartitionState(namespace, lock, fence)
        self.states[namespace] = state
        return state

    def install(self, stack: ExitStack) -> None:
        stages = pipeline(POLICY_PROJECTIONS[self.policy], scalar_field="author_id")
        stack.enter_context(patch.object(core_module, "NamespaceState", self.state))
        stack.enter_context(
            patch.object(stream_module, "build_change_stream_pipeline", lambda: stages)
        )
        stack.enter_context(
            patch.object(stream_module, "route_change_event", self.route)
        )

    def reset(self) -> None:
        with self.condition:
            self.applied.clear()
            self.route_cpu_ns = 0

    def drain(self, count: NonNegativeInt) -> None:
        with self.condition:
            complete = self.condition.wait_for(lambda: len(self.applied) >= count, 30)
            if not complete or len(self.applied) != count:
                raise RuntimeError("stream did not apply the scheduled writes exactly")

    def _bump(self, namespace: NamespaceId) -> None:
        try:
            state = self.states[namespace]
        except KeyError:
            return
        with state.lock:
            state.generation += 1
            state.find_families.clear()

    def _write(self, namespace: NamespaceId, event: Mapping[str, object]) -> None:
        if self.policy == "insert":
            try:
                by_author = self.partitions[namespace]
            except KeyError:
                return
            if event["operationType"] == "insert":
                partition = event["partition"]
                assert isinstance(partition, dict)
                if partition["known"]:
                    author = partition["value"]
                    if isinstance(author, int) and not isinstance(author, bool):
                        try:
                            guarded = by_author[author]
                        except KeyError:
                            return
                        self._bump(guarded)
                        return
            self.fallbacks[namespace].generation += 1
        elif self.policy == "fields":
            try:
                guarded = self.dependency_namespaces[namespace]
            except KeyError:
                return
            if event["operationType"] == "update":
                changes = event["changes"]
                assert isinstance(changes, dict)
                if changes["known"] and not any(
                    name == "author_id" or name.startswith("author_id.")
                    for name in changes["names"]
                ):
                    return
            self._bump(guarded)

    def route(
        self, cache: CacheCore, database: str, event: Mapping[str, object]
    ) -> bool:
        started = time.thread_time_ns()
        reopen = route_change_event(cache, database, event)
        operation = event["operationType"]
        if operation in {"insert", "update", "replace", "delete"}:
            namespace = event["ns"]
            assert isinstance(namespace, dict)
            self._write(NamespaceId(namespace["db"], namespace["coll"]), event)
            elapsed = time.thread_time_ns() - started
            with self.condition:
                self.route_cpu_ns += elapsed
                self.applied.append(time.monotonic())
                self.condition.notify_all()
        elif operation not in {"dropDatabase", "invalidate"}:
            for namespace in tuple(self.states):
                if "#" in namespace.collection:
                    cache.clear_namespace(namespace)
        return reopen
