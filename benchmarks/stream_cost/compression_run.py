from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from benchmarks.stream_cost.client import (
    BenchmarkClientTopologyConfig,
    WireCompressor,
    build_dedicated_client,
)
from benchmarks.stream_cost.compression_decision import evaluate_compression_decision
from benchmarks.stream_cost.compression_matrix import (
    STANDARD_COMPRESSION_WINDOWS,
    counterbalanced_mode_order,
    counterbalanced_path_order,
    require_minimum_compression_blocks,
)
from benchmarks.stream_cost.compression_matrix_runner import (
    CompressionWindowResult,
    run_compression_mode_block,
)
from benchmarks.stream_cost.compression_report import (
    CompressionBlockPlan,
    build_compression_report,
    validate_compression_report,
)
from benchmarks.stream_cost.config import (
    BenchmarkEnvironment,
    BenchmarkIdentity,
    Limitation,
)
from benchmarks.stream_cost.proxy import DirectPathByteProxy, DirectPathProxyConfig
from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pymongo import MongoClient

    from benchmarks.stream_cost.compression_matrix import CompressionWindowSpec
    from benchmarks.stream_cost.compressor_preflight import CompressorPreflightResult

_ADMIN_TOPOLOGY = BenchmarkClientTopologyConfig(
    tls_enabled=False,
    compressor=WireCompressor.NONE,
    discovery_enabled=False,
    shared_connections=False,
)


def _revision() -> str:
    git_path = shutil.which("git")
    if git_path is None:  # pragma: no cover - git always installed in CI
        raise RuntimeError("git is required to identify the benchmark revision")
    return subprocess.check_output(  # noqa: S603 - fixed git arguments
        # Git 2.55.0: https://git-scm.com/docs/git-rev-parse
        # --short=7: The default is effective core.abbrev, otherwise automatic length.
        # We override it because reports need a consistent minimum seven-character
        # identifier.
        [git_path, "rev-parse", "--short=7", "HEAD"],
        text=True,
    ).strip()


def _client_for_mode(
    proxy: DirectPathByteProxy, mode: WireCompressor
) -> MongoClient[dict[str, Any]]:
    uri = f"mongodb://127.0.0.1:{proxy.local_port}/?directConnection=true"
    topology = BenchmarkClientTopologyConfig(
        tls_enabled=False,
        compressor=mode,
        discovery_enabled=False,
        shared_connections=False,
    )
    return build_dedicated_client(uri, topology)


def _limitations(proxy: DirectPathByteProxy) -> tuple[Limitation, ...]:
    return (
        Limitation("container-cpu", "CPU is measured for the isolated container."),
        Limitation("direct-path-bytes", proxy.limitation),
        Limitation(
            "stream-minus-control",
            "The stream-minus-control CPU and byte deltas approximate the change "
            "stream's added cost; they are not an exact per-component attribution.",
        ),
        Limitation(
            "local-single-host",
            "Measurements were taken on a single isolated host and do not "
            "generalize to other hosts, deployments, or workloads.",
        ),
    )


def _run_block(
    block: CompressionBlockPlan,
    *,
    windows: Sequence[CompressionWindowSpec],
    admin_client: MongoClient[dict[str, Any]],
    replica_set: IsolatedReplicaSet,
    proxy: DirectPathByteProxy,
) -> tuple[
    dict[tuple[int, WireCompressor], CompressorPreflightResult],
    list[CompressionWindowResult],
]:
    negotiations: dict[tuple[int, WireCompressor], CompressorPreflightResult] = {}
    window_results: list[CompressionWindowResult] = []
    for mode in block.mode_order:
        with _client_for_mode(proxy, mode) as client:
            negotiation, results = run_compression_mode_block(
                windows,
                mode=mode,
                path_order=block.path_order,
                block_index=block.block_index,
                client=client,
                admin_client=admin_client,
                replica_set=replica_set,
                proxy=proxy,
                database_prefix=f"compression_block{block.block_index}_{mode.value}",
            )
        negotiations[block.block_index, mode] = negotiation
        window_results.extend(results)
    return negotiations, window_results


def run_compression_matrix(
    *,
    windows: Sequence[CompressionWindowSpec] = STANDARD_COMPRESSION_WINDOWS,
    block_count: int,
    limits: ResourceLimits,
) -> dict[str, object]:
    require_minimum_compression_blocks(block_count)
    blocks = [
        CompressionBlockPlan(
            block_index=block_index,
            mode_order=counterbalanced_mode_order(block_index),
            path_order=counterbalanced_path_order(block_index),
        )
        for block_index in range(block_count)
    ]

    negotiations: dict[tuple[int, WireCompressor], CompressorPreflightResult] = {}
    window_results: list[CompressionWindowResult] = []

    with IsolatedReplicaSet(limits) as replica_set:
        parsed_uri = urlparse(replica_set.uri)
        proxy_config = DirectPathProxyConfig(
            client_topology=_ADMIN_TOPOLOGY,
            upstream_host=parsed_uri.hostname or "127.0.0.1",
            upstream_port=parsed_uri.port or 27017,
        )
        with DirectPathByteProxy(proxy_config) as proxy:
            with build_dedicated_client(
                replica_set.uri, _ADMIN_TOPOLOGY
            ) as admin_client:
                mongodb_version = admin_client.server_info()["version"]
                for block in blocks:
                    block_negotiations, block_results = _run_block(
                        block,
                        windows=windows,
                        admin_client=admin_client,
                        replica_set=replica_set,
                        proxy=proxy,
                    )
                    negotiations.update(block_negotiations)
                    window_results.extend(block_results)

            identity = BenchmarkIdentity(
                revision=_revision(),
                library_version=version("client-query-cache"),
                python_version=platform.python_version(),
                pymongo_version=version("pymongo"),
            )
            environment = BenchmarkEnvironment(
                mongodb_version=mongodb_version,
                topology="isolated single-member replica set",
                member_count=1,
                resource_limits={"cpus": str(limits.cpus), "memory": limits.memory},
            )
            report = build_compression_report(
                identity=identity,
                environment=environment,
                windows=windows,
                blocks=blocks,
                negotiations=negotiations,
                window_results=window_results,
                limitations=_limitations(proxy),
            )

    validate_compression_report(report)
    return report


def main() -> None:  # pragma: no cover - manual CLI entry point, unused in CI
    parser = argparse.ArgumentParser(
        description="Run the isolated four-mode wire compression matrix"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--blocks", type=int, default=4)
    parser.add_argument("--cpus", type=float, default=1.0)
    parser.add_argument("--memory", default="1g")
    arguments = parser.parse_args()
    report = run_compression_matrix(
        block_count=arguments.blocks,
        limits=ResourceLimits(cpus=arguments.cpus, memory=arguments.memory),
    )
    decision = evaluate_compression_decision(report)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    decision_path = arguments.output.with_name(arguments.output.stem + ".decision.json")
    decision_path.write_text(
        json.dumps(
            {
                "recommended_mode": decision.recommended_mode.value,
                "inconclusive": decision.inconclusive,
                "rationale": decision.rationale,
                "evidence": [
                    {
                        "mode": item.mode.value,
                        "qualifies": item.qualifies,
                        "idle_noisy": item.idle_noisy,
                        "failures": list(item.failures),
                        "median_stream_total_bytes": item.median_stream_total_bytes,
                        "median_added_cpu_seconds": item.median_added_cpu_seconds,
                    }
                    for item in decision.evidence
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
