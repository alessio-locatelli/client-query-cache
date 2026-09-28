from __future__ import annotations

import argparse
import contextlib
import json
import platform
import shutil
import subprocess
import time
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from benchmarks.stream_cost.client import (
    BenchmarkClientTopologyConfig,
    build_dedicated_client,
)
from benchmarks.stream_cost.config import (
    BenchmarkConfig,
    BenchmarkEnvironment,
    BenchmarkIdentity,
    Limitation,
    WorkloadParameters,
)
from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.measurement import (
    ChangeStreamCostComparison,
    measure_controlled,
    snapshot_logical_metrics,
)
from benchmarks.stream_cost.proxy import DirectPathByteProxy, DirectPathProxyConfig
from benchmarks.stream_cost.report import build_report, validate_report
from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits
from benchmarks.stream_cost.workload import (
    STANDARD_WORKLOAD_VARIANTS,
    SeededDataset,
    WorkloadKind,
    WorkloadVariant,
    WorkloadVariantOutcome,
    insert_dataset,
    issue_writes,
    perform_cache_only_reads,
    perform_raw_only_reads,
    run_workload_variant,
    sample_operation_ids,
    seed_dataset,
    verify_primed,
)
from client_query_cache.synchronous.manager import CacheManager

if TYPE_CHECKING:
    from pymongo import MongoClient
    from pymongo.synchronous.collection import Collection

    from client_query_cache.synchronous.collection import CachedCollection

_STREAM_SETTLE_TIMEOUT_SECONDS = 15.0
_STREAM_SETTLE_POLL_SECONDS = 0.02


def _wait_for_invalidations_to_settle(
    manager: CacheManager[dict[str, Any]],
    database_name: str,
    expected_count: int,
    *,
    context: str,
) -> None:
    deadline = time.monotonic() + _STREAM_SETTLE_TIMEOUT_SECONDS
    while (
        manager.cache_core.stream_cost_snapshot(database_name).invalidations
        < expected_count
    ):
        if time.monotonic() >= deadline:
            message = (
                f"stream invalidations did not settle for {context} "
                f"within {_STREAM_SETTLE_TIMEOUT_SECONDS:.0f} seconds"
            )
            raise BenchmarkSetupError(message)
        time.sleep(_STREAM_SETTLE_POLL_SECONDS)


def _revision() -> str:
    git_path = shutil.which("git")
    if git_path is None:
        raise RuntimeError("git is required to identify the benchmark revision")
    return subprocess.check_output(  # noqa: S603 - fixed git arguments
        [git_path, "rev-parse", "--short=7", "HEAD"], text=True, shell=False
    ).strip()


def run_standard_matrix(
    output_dir: Path, *, limits: ResourceLimits, direct_path_proxy: bool = False
) -> tuple[Path, ...]:
    output_dir.mkdir(parents=True, exist_ok=True)
    client_topology = BenchmarkClientTopologyConfig(
        tls_enabled=False,
        compression_enabled=False,
        discovery_enabled=False,
        shared_connections=False,
    )
    report_paths: list[Path] = []
    with IsolatedReplicaSet(limits) as replica_set:
        parsed_uri = urlparse(replica_set.uri)
        proxy_context = (
            DirectPathByteProxy(
                DirectPathProxyConfig(
                    client_topology=client_topology,
                    upstream_host=parsed_uri.hostname or "127.0.0.1",
                    upstream_port=parsed_uri.port or 27017,
                )
            )
            if direct_path_proxy
            else contextlib.nullcontext(None)
        )
        with proxy_context as proxy:
            uri = (
                f"mongodb://127.0.0.1:{proxy.local_port}/?directConnection=true"
                if proxy is not None
                else replica_set.uri
            )
            client = build_dedicated_client(uri, client_topology)
            try:
                report_paths.extend(
                    _run_matrix_with_client(
                        client,
                        replica_set=replica_set,
                        proxy=proxy,
                        limits=limits,
                        output_dir=output_dir,
                    )
                )
            finally:
                client.close()
    return tuple(report_paths)


def _run_matrix_with_client(
    client: MongoClient[dict[str, Any]],
    *,
    replica_set: IsolatedReplicaSet,
    proxy: DirectPathByteProxy | None,
    limits: ResourceLimits,
    output_dir: Path,
) -> tuple[Path, ...]:
    report_paths: list[Path] = []
    mongodb_version = client.server_info()["version"]
    for variant in STANDARD_WORKLOAD_VARIANTS:
        report_path = _run_variant(
            variant,
            client=client,
            replica_set=replica_set,
            proxy=proxy,
            mongodb_version=mongodb_version,
            limits=limits,
            output_dir=output_dir,
        )
        report_paths.append(report_path)
    return tuple(report_paths)


def _measure_change_stream_cost_comparison(
    variant: WorkloadVariant,
    dataset: SeededDataset,
    *,
    client: MongoClient[dict[str, Any]],
    replica_set: IsolatedReplicaSet,
    proxy: DirectPathByteProxy | None,
    database_name: str,
) -> ChangeStreamCostComparison:
    database = client[database_name]
    read_ids = sample_operation_ids(dataset, variant.sampling.reads, seed=variant.seed)

    raw_collection_name = "measured_change_stream_cost_raw"
    database.drop_collection(raw_collection_name)
    raw_only_collection = database[raw_collection_name]
    insert_dataset(raw_only_collection, dataset)

    def _raw_only_operation() -> None:
        perform_raw_only_reads(raw_only_collection, read_ids)
        issue_writes(
            raw_only_collection, dataset, variant.sampling.writes, seed=variant.seed + 1
        )

    _, raw_measurement = measure_controlled(
        _raw_only_operation, replica_set=replica_set, proxy=proxy
    )

    cache_collection_name = "measured_change_stream_cost_cache"
    database.drop_collection(cache_collection_name)
    cache_only_raw_collection = database[cache_collection_name]
    insert_dataset(cache_only_raw_collection, dataset)
    with CacheManager(client) as manager:
        cache_only_collection = manager[database_name][cache_collection_name]
        before = manager.cache_core.snapshot()
        for _ in range(variant.warmup.reads):
            for document_id in read_ids:
                cache_only_collection.find_one({"_id": document_id})
        after = manager.cache_core.snapshot()
        verify_primed(before, after, variant_name=f"{variant.name}-change-stream-cost")

        def _cache_only_operation() -> None:
            perform_cache_only_reads(cache_only_collection, read_ids)
            writes_issued = issue_writes(
                cache_only_raw_collection,
                dataset,
                variant.sampling.writes,
                seed=variant.seed + 1,
            )
            _wait_for_invalidations_to_settle(
                manager,
                database_name,
                writes_issued,
                context=f"{variant.name}-change-stream-cost",
            )

        _, cache_measurement = measure_controlled(
            _cache_only_operation, replica_set=replica_set, proxy=proxy
        )

    return ChangeStreamCostComparison(raw=raw_measurement, cache=cache_measurement)


def _run_variant(
    variant: WorkloadVariant,
    *,
    client: MongoClient[dict[str, Any]],
    replica_set: IsolatedReplicaSet,
    proxy: DirectPathByteProxy | None,
    mongodb_version: str,
    limits: ResourceLimits,
    output_dir: Path,
) -> Path:
    database_name = f"stream_cost_{variant.name}"
    database = client[database_name]
    database.drop_collection("measured")
    raw_collection = database["measured"]
    dataset = seed_dataset(variant)
    insert_dataset(raw_collection, dataset)
    with CacheManager(client) as manager:
        cache_collection = manager[database_name]["measured"]
        outcome, measurement = measure_controlled(
            lambda: _sample_variant(
                manager,
                raw_collection,
                cache_collection,
                variant,
                dataset,
                database_name=database_name,
            ),
            replica_set=replica_set,
            proxy=proxy,
        )
        logical_metrics = snapshot_logical_metrics(manager)

    change_stream_cost = (
        _measure_change_stream_cost_comparison(
            variant,
            dataset,
            client=client,
            replica_set=replica_set,
            proxy=proxy,
            database_name=database_name,
        )
        if variant.kind is WorkloadKind.BALANCED
        else None
    )

    config = BenchmarkConfig(
        identity=BenchmarkIdentity(
            revision=_revision(),
            library_version=version("client-query-cache"),
            python_version=platform.python_version(),
            pymongo_version=version("pymongo"),
        ),
        environment=BenchmarkEnvironment(
            mongodb_version=mongodb_version,
            topology="isolated single-member replica set",
            member_count=1,
            resource_limits={"cpus": str(limits.cpus), "memory": limits.memory},
        ),
        workload=WorkloadParameters(
            name=variant.name,
            parameters={
                "seed": variant.seed,
                "document_count": variant.document_count,
                "document_size_profile": variant.data_size.name,
                "warmup_reads": variant.warmup.reads,
                "warmup_writes": variant.warmup.writes,
                "sample_reads": variant.sampling.reads,
                "sample_writes": variant.sampling.writes,
            },
        ),
        limitations=(
            Limitation(
                "container-cpu",
                "CPU is measured for the isolated MongoDB container on this host.",
            ),
            Limitation(
                "logical-bytes",
                "Logical event bytes describe decoded events, not wire traffic.",
            ),
            Limitation(
                "clock-skew",
                "Raw event delivery lag includes server-to-host clock skew.",
            ),
            *(
                (Limitation("direct-path-bytes", proxy.limitation),)
                if proxy is not None
                else ()
            ),
            *(
                (
                    Limitation(
                        "change-stream-cost-bytes",
                        "change_stream_cost_comparison's container_cpu_seconds and "
                        "direct_path_bytes each cover the whole raw-path or "
                        "cache-path run (sampled reads, shared writes, and - for "
                        "the cache path - change-stream polling), not the change "
                        "stream in isolation; only the delta between the two paths "
                        "approximates the stream's added cost.",
                    ),
                )
                if change_stream_cost is not None
                else ()
            ),
        ),
    )
    report = build_report(
        config,
        measurement,
        outcome,
        logical_metrics,
        change_stream_cost=change_stream_cost,
    )
    validate_report(report)
    report_path = output_dir / f"{variant.name}.report.v1.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report_path


def _sample_variant(
    manager: CacheManager[dict[str, Any]],
    raw_collection: Collection[dict[str, Any]],
    cache_collection: CachedCollection[dict[str, Any]],
    variant: WorkloadVariant,
    dataset: SeededDataset,
    *,
    database_name: str,
) -> WorkloadVariantOutcome:
    outcome = run_workload_variant(
        manager, raw_collection, cache_collection, variant, dataset
    )
    if outcome.writes_issued:
        _wait_for_invalidations_to_settle(
            manager, database_name, outcome.writes_issued, context=variant.name
        )
    return outcome


def main() -> None:
    parser = argparse.ArgumentParser(description="Run controlled stream-cost workloads")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cpus", type=float, default=1.0)
    parser.add_argument("--memory", default="1g")
    parser.add_argument("--direct-path-proxy", action="store_true")
    arguments = parser.parse_args()
    run_standard_matrix(
        arguments.output_dir,
        limits=ResourceLimits(cpus=arguments.cpus, memory=arguments.memory),
        direct_path_proxy=arguments.direct_path_proxy,
    )


if __name__ == "__main__":
    main()
