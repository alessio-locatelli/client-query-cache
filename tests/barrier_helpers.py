from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

from pymongo import monitoring

if TYPE_CHECKING:
    from tests.conftest import MongoDbUri

BARRIER_TIMEOUT_SECONDS = 30
SPREAD_DOCUMENT_COUNT = 8


class Topology(NamedTuple):
    uri: MongoDbUri
    sharded: bool


class AggregateRecorder(monitoring.CommandListener):
    def __init__(self) -> None:
        self.aggregates: list[dict[str, Any]] = []

    def started(self, event: monitoring.CommandStartedEvent) -> None:
        if event.command_name == "aggregate":
            self.aggregates.append(dict(event.command))

    def succeeded(self, event: monitoring.CommandSucceededEvent) -> None:
        pass

    def failed(self, event: monitoring.CommandFailedEvent) -> None:
        pass

    def barrier_aggregates(self) -> list[dict[str, Any]]:
        return [
            command
            for command in self.aggregates
            if "startAtOperationTime" in command["pipeline"][0]["$changeStream"]
        ]


def spread_documents(labels: list[str]) -> list[dict[str, Any]]:
    return [
        {"_id": index, "group": "spread", "label": label, "value": 0}
        for index, label in enumerate(labels)
    ]
