from __future__ import annotations

import argparse
import gc
import json
import random
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from bson import ObjectId

from client_query_cache import CacheCoreConfig
from client_query_cache import _shared_index as native
from client_query_cache._core.codec import codec_fingerprint, encode_value
from client_query_cache._core.find_one_reads import (
    find_one_read_shape_key,
    generic_find_one_discriminator,
)
from client_query_cache._core.keys import canonical_alias_key
from client_query_cache._core.order_sensitive_keys import canonical_discriminator_key
from research.native_build_profile.compare import (
    BOOTSTRAP_RESAMPLES,
    improvement_percent,
    interval,
)
from research.native_build_profile.measure import batch_nanoseconds, passes_per_batch
from scripts.pgo_training import (
    CLEANUP,
    NAMESPACE,
    OPTIONS,
    RESIDENT_KEYS,
    SMALL_BYTES,
    documents,
    read_shape,
    verified,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from client_query_cache._core.keys import AliasKey
    from scripts.pgo_training import Workload

type Builder = Callable[[Limits], Workload]

BUDGET_BYTES = 1024 * 1024
WINDOWS = 16
GENEROUS_ENTRIES = 1_000_000
GENEROUS_KEY_BYTES = 1024 * 1024
PRESSURE_ENTRIES = 2048


@dataclass(frozen=True, slots=True)
class Limits:
    max_entries: int | None = None
    max_key_bytes: int | None = None


CONFIGS: dict[str, Limits] = {
    "disabled": Limits(),
    "count": Limits(max_entries=GENEROUS_ENTRIES),
    "key": Limits(max_key_bytes=GENEROUS_KEY_BYTES),
    "both": Limits(GENEROUS_ENTRIES, GENEROUS_KEY_BYTES),
    "count_pressure": Limits(max_entries=PRESSURE_ENTRIES),
    "both_pressure": Limits(PRESSURE_ENTRIES, GENEROUS_KEY_BYTES),
}


class Account(NamedTuple):
    identity: ObjectId
    alias: AliasKey


@dataclass(frozen=True, slots=True)
class Sample:
    config: str
    workload: str
    round_index: int
    nanoseconds: float


def limited_core(limits: Limits) -> native.LocalCacheCore:
    return native.LocalCacheCore(
        CacheCoreConfig(
            enable_telemetry=True,
            budget_bytes=BUDGET_BYTES,
            max_entry_bytes=BUDGET_BYTES // 4,
            max_entries=limits.max_entries,
            max_key_bytes=limits.max_key_bytes,
        )
    )


def generic_discriminators() -> list[object]:
    shape = find_one_read_shape_key(None, None, None, codec_fingerprint(OPTIONS))
    return [
        generic_find_one_discriminator(
            canonical_discriminator_key({"code": f"C{index:07d}"}), shape, 0
        )
        for index in range(WINDOWS * RESIDENT_KEYS)
    ]


def windowed[Item](
    items: list[Item], run_window: Callable[[list[Item]], None]
) -> Workload:
    position = 0

    def run() -> None:
        nonlocal position
        run_window(items[position : position + RESIDENT_KEYS])
        position = (position + RESIDENT_KEYS) % len(items)

    for _ in range(WINDOWS + 1):
        run()
    return run, RESIDENT_KEYS


def generic_miss_admission(limits: Limits) -> Workload:
    payload = encode_value(documents(SMALL_BYTES, 1)[0], OPTIONS)
    core = limited_core(limits)
    capture = core.capture_namespace_generation
    admit = core.admit_namespace_encoded

    def run_window(window: list[object]) -> None:
        for discriminator in window:
            admit(capture(NAMESPACE), discriminator, payload)

    return windowed(generic_discriminators(), run_window)


def identity_alias_admission(limits: Limits) -> Workload:
    payload = encode_value(documents(SMALL_BYTES, 1)[0], OPTIONS)
    shape = read_shape()
    core = limited_core(limits)
    begin = core.begin_identity_admission
    admit = core.admit_identity_encoded
    pairs = [
        Account(
            ObjectId(), canonical_alias_key("email", f"user-{index}@example.test", None)
        )
        for index in range(WINDOWS * RESIDENT_KEYS)
    ]

    def run_window(window: list[Account]) -> None:
        for account in window:
            admit(
                begin(NAMESPACE, account.identity), shape, payload, alias=account.alias
            )

    return windowed(pairs, run_window)


def unique_key_admission(limits: Limits) -> Workload:
    document = documents(SMALL_BYTES, 1)[0]
    shape = read_shape()
    core = limited_core(limits)
    capture = core.capture_namespace_generation
    admit = core.admit_unique_key_match
    entries = []
    for index in range(WINDOWS * RESIDENT_KEYS):
        alias = canonical_alias_key("email", f"user-{index}@example.test", None)
        entries.append(Account(ObjectId(), alias))

    def run_window(window: list[Account]) -> None:
        for account in window:
            admit(
                capture(NAMESPACE),
                (account.alias, shape),
                account.identity,
                shape,
                document,
                alias=account.alias,
            )

    return windowed(entries, run_window)


def generic_hit(limits: Limits) -> Workload:
    payload = encode_value(documents(SMALL_BYTES, 1)[0], OPTIONS)
    core = limited_core(limits)
    discriminators = generic_discriminators()[:RESIDENT_KEYS]
    for discriminator in discriminators:
        core.admit_namespace_encoded(
            core.capture_namespace_generation(NAMESPACE), discriminator, payload
        )
    lookup = core.lookup_namespace_encoded

    def run() -> None:
        for discriminator in discriminators:
            lookup(NAMESPACE, discriminator)

    verified(core, run, hits=len(discriminators))
    return run, len(discriminators)


def unique_key_hit(limits: Limits) -> Workload:
    document = documents(SMALL_BYTES, 1)[0]
    shape = read_shape()
    core = limited_core(limits)
    entries = []
    for index in range(RESIDENT_KEYS):
        alias = canonical_alias_key("email", f"user-{index}@example.test", None)
        identity = ObjectId()
        core.admit_unique_key_match(
            core.capture_namespace_generation(NAMESPACE),
            (alias, shape),
            identity,
            shape,
            document,
            alias=alias,
        )
        entries.append(("email", f"user-{index}@example.test", identity))
    resolve = core.resolve_alias
    lookup = (
        core.lookup_identity_deferred if limits.max_entries else core.lookup_identity
    )

    def run() -> None:
        for field, value, _identity in entries:
            resolved = resolve(NAMESPACE, field, value, None)
            lookup(NAMESPACE, resolved, shape, codec_options=OPTIONS)

    run()
    return run, len(entries)


WORKLOADS: dict[str, Builder] = {
    "generic_miss_admission": generic_miss_admission,
    "identity_alias_admission": identity_alias_admission,
    "unique_key_admission": unique_key_admission,
    "generic_hit": generic_hit,
    "unique_key_hit": unique_key_hit,
}


def measure_once(builder: Builder, limits: Limits) -> float:
    run, operations = builder(limits)
    passes = passes_per_batch(run)
    gc.collect()
    gc.disable()
    try:
        samples = list(batch_nanoseconds(run, operations, passes))
    finally:
        gc.enable()
    return statistics.median(samples)


def collect(
    workloads: list[str], configs: list[str], rounds: int, seed: int
) -> list[Sample]:
    generator = random.Random(seed)
    samples: list[Sample] = []
    for round_index in range(rounds):
        for workload in workloads:
            order = list(configs)
            generator.shuffle(order)
            for config in order:
                nanoseconds = measure_once(WORKLOADS[workload], CONFIGS[config])
                samples.append(Sample(config, workload, round_index, nanoseconds))
            print(f"round {round_index} {workload}", file=sys.stderr, flush=True)
    return samples


def summarize(
    samples: list[Sample], workloads: list[str], configs: list[str], seed: int
) -> dict[str, dict[str, dict[str, float]]]:
    generator = random.Random(seed)
    table: dict[str, dict[str, dict[str, float]]] = {}
    for workload in workloads:
        rows = {
            (s.config, s.round_index): s.nanoseconds
            for s in samples
            if s.workload == workload
        }
        rounds = sorted({round_index for _config, round_index in rows})
        table[workload] = {}
        for config in configs:
            paired = [
                -improvement_percent(rows["disabled", index], rows[config, index])
                for index in rounds
            ]
            low, high = interval(paired, generator)
            table[workload][config] = {
                "nanoseconds": statistics.median(
                    rows[config, index] for index in rounds
                ),
                "change_percent": statistics.median(paired),
                "low": low,
                "high": high,
            }
    return table


def markdown(table: dict[str, dict[str, dict[str, float]]], configs: list[str]) -> str:
    lines = [
        "| Workload | " + " | ".join(configs) + " |",
        "| --- | " + " | ".join("---:" for _ in configs) + " |",
    ]
    for workload, row in table.items():
        cells = []
        for config in configs:
            entry = row[config]
            cell = f"{entry['nanoseconds']:.0f} ns"
            if config != "disabled":
                cell += (
                    f" ({entry['change_percent']:+.1f}% "
                    f"[{entry['low']:+.1f}, {entry['high']:+.1f}])"
                )
            cells.append(cell)
        lines.append(f"| {workload} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Time native admission and hits with each retention limit enabled"
    )
    parser.add_argument("--rounds", type=int, default=9)
    parser.add_argument("--seed", type=int, default=20261103)
    parser.add_argument("--workloads", nargs="*", default=list(WORKLOADS))
    parser.add_argument("--configs", nargs="*", default=list(CONFIGS))
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    configs = ["disabled", *[c for c in arguments.configs if c != "disabled"]]
    with CLEANUP:
        samples = collect(
            arguments.workloads, configs, arguments.rounds, arguments.seed
        )
    table = summarize(samples, arguments.workloads, configs, arguments.seed)
    arguments.output.write_text(json.dumps(table, indent=2) + "\n", encoding="utf-8")
    print(markdown(table, configs))
    print(f"resamples={BOOTSTRAP_RESAMPLES} rounds={arguments.rounds}")


if __name__ == "__main__":
    main()
