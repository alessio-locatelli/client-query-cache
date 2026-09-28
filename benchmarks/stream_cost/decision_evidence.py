from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import time
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, Any

from benchmarks.stream_cost.bootstrap import (
    absolute_threshold_decisive,
    block_bootstrap_percentile_ci,
    bonferroni_delta_interval,
    delta_threshold_decisive,
    expand_with_uncertainty,
)
from benchmarks.stream_cost.calibration import TopologyChangeListener
from benchmarks.stream_cost.client import (
    BenchmarkClientTopologyConfig,
    WireCompressor,
    build_dedicated_client,
)
from benchmarks.stream_cost.consolidated_stream import (
    ConsolidatedStreamPairConfig,
)
from benchmarks.stream_cost.oversized_result import measure_oversized_result_workload
from benchmarks.stream_cost.pair_runner import PairResult, run_consolidated_stream_pairs
from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits
from benchmarks.stream_cost.workload import verify_oversized_primed
from client_query_cache._core.manager import CacheCoreConfig
from client_query_cache._core.stream_cost import LagCaptureWindowConfig
from client_query_cache.synchronous.manager import CacheManager

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pymongo import MongoClient

_PREREGISTRATION = (
    Path(__file__).parents[2] / "reports/stream-cost/v1/decision-pre-registration.json"
)
_TOPOLOGY = BenchmarkClientTopologyConfig(
    tls_enabled=False,
    compressor=WireCompressor.NONE,
    discovery_enabled=False,
    shared_connections=False,
)


def _pair_evidence(
    pair: PairResult, config: Mapping[str, Any], *, pair_index: int
) -> dict[str, object]:
    offset = pair.calibration.initial.offset_seconds
    uncertainty = pair.calibration.total_uncertainty_seconds
    percentile = config["acceptable_lag_percentile"]
    confidence = config["bootstrap_confidence_level"]
    resamples = config["bootstrap_resample_count"]
    seed = config["bootstrap_seed"] + pair_index * 10
    corrected = {
        "control": tuple(
            tuple(value + offset for value in window)
            for window in pair.control.raw_lag_windows
        ),
        "loaded": tuple(
            tuple(value + offset for value in window)
            for window in pair.loaded.raw_lag_windows
        ),
    }
    control_ci = block_bootstrap_percentile_ci(
        corrected["control"],
        percentile=percentile,
        confidence_level=confidence,
        resample_count=resamples,
        seed=seed,
    )
    loaded_ci = block_bootstrap_percentile_ci(
        corrected["loaded"],
        percentile=percentile,
        confidence_level=confidence,
        resample_count=resamples,
        seed=seed + 1,
    )
    adjusted_delta = (
        loaded_ci.point_estimate - control_ci.point_estimate + 2 * uncertainty
    )
    delta_ci = bonferroni_delta_interval(
        corrected["control"],
        corrected["loaded"],
        percentile=percentile,
        confidence_level=confidence,
        resample_count=resamples,
        seed=seed + 2,
        delta_seconds=adjusted_delta,
    )
    control_healthy = absolute_threshold_decisive(
        control_ci,
        config["acceptable_lag_threshold_seconds"],
        total_uncertainty_seconds=uncertainty,
    )
    loaded_healthy = absolute_threshold_decisive(
        loaded_ci,
        config["acceptable_lag_threshold_seconds"],
        total_uncertainty_seconds=uncertainty,
    )
    delta_healthy = delta_threshold_decisive(
        delta_ci, config["meaningfully_worse_absolute_delta_threshold_seconds"]
    )
    return {
        "pair_index": pair_index,
        "clock_offset_seconds": offset,
        "clock_initial_uncertainty_seconds": (
            pair.calibration.initial.uncertainty_seconds
        ),
        "clock_total_uncertainty_seconds": uncertainty,
        "calibration_offsets_seconds": [
            point.selected.offset_seconds for point in pair.calibration.points
        ],
        "control": {
            "relevant_writes": pair.control.relevant_write_count,
            "unrelated_writes_during_window": (
                pair.control.unrelated_write_count_during_window
            ),
            "raw_lag_windows_seconds": pair.control.raw_lag_windows,
            "corrected_lag_windows_seconds": corrected["control"],
            "percentile_interval_seconds": asdict(control_ci),
            "uncertainty_expanded_interval_seconds": asdict(
                expand_with_uncertainty(control_ci, uncertainty)
            ),
            "absolute_threshold_met": control_healthy,
        },
        "loaded": {
            "relevant_writes": pair.loaded.relevant_write_count,
            "unrelated_writes_during_window": (
                pair.loaded.unrelated_write_count_during_window
            ),
            "raw_lag_windows_seconds": pair.loaded.raw_lag_windows,
            "corrected_lag_windows_seconds": corrected["loaded"],
            "percentile_interval_seconds": asdict(loaded_ci),
            "uncertainty_expanded_interval_seconds": asdict(
                expand_with_uncertainty(loaded_ci, uncertainty)
            ),
            "absolute_threshold_met": loaded_healthy,
        },
        "uncertainty_adjusted_delta_interval_seconds": asdict(delta_ci),
        "delta_threshold_met": delta_healthy,
        "healthy": control_healthy and loaded_healthy and delta_healthy,
    }


def _consolidated_evidence(
    client: MongoClient[dict[str, Any]],
    listener: TopologyChangeListener,
    config: Mapping[str, Any],
) -> dict[str, object]:
    pair_config = ConsolidatedStreamPairConfig(
        acceptable_lag_percentile=config["acceptable_lag_percentile"],
        acceptable_lag_threshold_seconds=config["acceptable_lag_threshold_seconds"],
        relevant_write_count=config["relevant_write_count"],
        relevant_write_schedule_tolerance_seconds=config[
            "relevant_write_schedule_tolerance_seconds"
        ],
        relevant_write_count_tolerance=config["relevant_write_count_tolerance"],
        unrelated_write_minimum_count=config["unrelated_write_minimum_count"],
        unrelated_write_interval_seconds=config["unrelated_write_interval_seconds"],
        clock_drift_tolerance_seconds=config["clock_drift_tolerance_seconds"],
        calibration_cadence_seconds=config["calibration_cadence_seconds"],
        pair_count=config["pair_count"],
        warmup_duration_seconds=config["warmup_duration_seconds"],
    )
    schedule = tuple(
        (index + 1) * config["relevant_write_interval_seconds"]
        for index in range(config["relevant_write_count"])
    )
    lag_config = LagCaptureWindowConfig(
        window_count=config["lag_capture_window_count"],
        events_per_window=config["lag_capture_events_per_window"],
        min_separation_events=config["lag_capture_min_separation_events"],
    )
    pairs = run_consolidated_stream_pairs(
        client,
        listener,
        database=config["database"],
        relevant_collection_names=config["relevant_collections"],
        unrelated_collection_name=config["unrelated_collection"],
        config=pair_config,
        schedule=schedule,
        cache_config=CacheCoreConfig(lag_capture_window_config=lag_config),
    )
    pair_evidence = [
        _pair_evidence(pair, config, pair_index=index)
        for index, pair in enumerate(pairs)
    ]
    pipeline_healthy = all(pair["healthy"] for pair in pair_evidence)
    return {
        "schedule_offsets_seconds": schedule,
        "collection_to_stream": dict.fromkeys(
            config["relevant_collections"], config["database"]
        ),
        "stream_count": 1,
        "pairs": pair_evidence,
        "healthy": pipeline_healthy,
        "decision": (
            "keep_shipped_serial_database_router"
            if pipeline_healthy
            else "open_router_stage_instrumentation_followup"
        ),
        "limitation": (
            "A clock step and reversion entirely between two calibration samples "
            "cannot be detected; a healthy conclusion assumes none occurred. "
            "Lag includes server and transport time, not only router dispatch."
        ),
    }


def _oversized_evidence(
    client: MongoClient[dict[str, Any]], config: Mapping[str, Any]
) -> dict[str, object]:
    documents = [
        {"_id": index, "padding": "x" * config["document_padding_bytes"]}
        for index in range(config["document_count"])
    ]
    client[config["database"]][config["collection"]].insert_many(documents)
    cache_config = CacheCoreConfig(
        shared_budget_bytes=config["max_entry_bytes"] * 4,
        max_entry_bytes=config["max_entry_bytes"],
    )
    with CacheManager(client, cache_config=cache_config) as manager:
        collection = manager[config["database"]][config["collection"]]
        before = manager.cache_core.snapshot()
        measurement = measure_oversized_result_workload(
            lambda: collection.find({}),
            max_entry_bytes=config["max_entry_bytes"],
            codec_options=collection.raw.codec_options,
            repetitions=config["encoder_repetitions"],
            acceptable_savings_threshold_seconds=config[
                "acceptable_savings_threshold_seconds"
            ],
        )
        after = manager.cache_core.snapshot()
        verify_oversized_primed(before, after, variant_name="oversized-result")
    savings = measurement.savings
    return {
        "oversized_bypass_delta": (
            after.oversized_bypasses - before.oversized_bypasses
        ),
        "end_to_end_cost_seconds": measurement.end_to_end_cost_seconds,
        "crossover_prefix_length": savings.prefix_length,
        "prefix_encoder_costs_seconds": savings.prefix_costs_seconds,
        "full_encoder_costs_seconds": savings.full_costs_seconds,
        "prefix_encoder_median_seconds": savings.prefix_cost_seconds,
        "full_encoder_median_seconds": savings.full_cost_seconds,
        "encoder_savings_seconds": savings.savings_seconds,
        "meets_acceptable_savings_threshold": (
            savings.meets_acceptable_savings_threshold
        ),
        "decision": (
            "open_incremental_admission_prototype_followup"
            if savings.meets_acceptable_savings_threshold
            else "leave_full_materialization_as_cost_benefit_judgment"
        ),
        "limitation": (
            "This compares one-shot encoder calls on different input sizes. "
            "It does not bound a real incremental encoder's cost."
        ),
    }


def run_decision_evidence() -> dict[str, object]:
    preregistration = json.loads(_PREREGISTRATION.read_text())
    limits = ResourceLimits(
        cpus=preregistration["topology"]["cpus"],
        memory=preregistration["topology"]["memory"],
    )
    listener = TopologyChangeListener()
    with IsolatedReplicaSet(limits) as replica_set:
        client = build_dedicated_client(
            replica_set.uri, _TOPOLOGY, event_listeners=[listener]
        )
        try:
            started = time.monotonic()
            process_cpu_started = time.process_time()
            container_cpu_started = replica_set.container_cpu_usage_seconds()
            consolidated = _consolidated_evidence(
                client, listener, preregistration["consolidated_stream"]
            )
            oversized = _oversized_evidence(client, preregistration["oversized_result"])
            container_cpu_seconds = (
                replica_set.container_cpu_usage_seconds() - container_cpu_started
            )
            process_cpu_seconds = time.process_time() - process_cpu_started
            elapsed_seconds = time.monotonic() - started
            mongodb_version = client.server_info()["version"]
        finally:
            client.close()
    git_path = shutil.which("git")
    if git_path is None:
        raise RuntimeError("git is required to identify the benchmark revision")
    return {
        "schema_version": 2,
        "revision": subprocess.check_output(  # noqa: S603 - fixed git arguments
            [git_path, "rev-parse", "--short=7", "HEAD"], text=True, shell=False
        ).strip(),
        "versions": {
            "python": platform.python_version(),
            "pymongo": version("pymongo"),
            "client_query_cache": version("client-query-cache"),
            "mongodb": mongodb_version,
        },
        "topology": "isolated single-member replica set",
        "preregistration": preregistration,
        "aggregate_wall_seconds": elapsed_seconds,
        "benchmark_process_cpu_seconds": process_cpu_seconds,
        "mongodb_container_cpu_seconds": container_cpu_seconds,
        "consolidated_stream": consolidated,
        "oversized_result": oversized,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run pre-registered decision workloads"
    )
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(run_decision_evidence(), indent=2, sort_keys=True) + "\n"
    )


if __name__ == "__main__":
    main()
