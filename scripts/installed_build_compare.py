import hashlib
import json
import pathlib
import random
import statistics
import subprocess
import sys
import tempfile
from itertools import product

from benchmarks.stream_cost.guard_runner import RevisionEnvironment, measure_paired_case
from benchmarks.stream_cost.guard_workload import CASE_NAMES, PROFILES
from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits

PROBE = pathlib.Path(__file__).with_name("installed_build_probe.py")
BUILDS = ("main", "cand")
METRICS = (
    "import_seconds",
    "manager_seconds",
    "shared_import_seconds",
    "cpu_seconds",
    "rss_import_kib",
    "rss_manager_kib",
    "rss_shared_kib",
)
WORKLOAD_FILES = ("errors.py", "generators.py", "guard_workload.py")


def bootstrap_interval(ratios: list[float], draws: int = 4000) -> tuple[float, float]:
    generator = random.Random(2026)
    medians = sorted(
        statistics.median(generator.choices(ratios, k=len(ratios)))
        for _ in range(draws)
    )
    return medians[int(0.025 * draws)], medians[int(0.975 * draws)]


def run_probe(work: pathlib.Path, build: str) -> dict[str, float]:
    with tempfile.TemporaryDirectory() as neutral_directory:
        completed = subprocess.run(  # noqa: S603 - argv is built from local paths
            [
                str(work / f"venv-{build}" / "bin" / "python"),
                "-I",
                str(PROBE),
                "startup-child",
            ],
            capture_output=True,
            text=True,
            check=True,
            cwd=neutral_directory,
        )
    return json.loads(completed.stdout)


def startup(work: pathlib.Path, pairs: int) -> None:
    samples: dict[str, dict[str, list[float]]] = {
        build: {metric: [] for metric in METRICS} for build in BUILDS
    }
    for build in BUILDS:
        run_probe(work, build)
    for index in range(pairs):
        for build in BUILDS[:: 1 if index % 2 == 0 else -1]:
            sample = run_probe(work, build)
            for metric in METRICS:
                samples[build][metric].append(sample[metric])
    print(f"pairs={pairs}")
    for metric in METRICS:
        main, cand = samples["main"][metric], samples["cand"][metric]
        ratios = [c / m for m, c in zip(main, cand, strict=True)]
        low, high = bootstrap_interval(ratios)
        print(
            f"{metric:24s} main median {statistics.median(main):12.6g}  "
            f"cand median {statistics.median(cand):12.6g}  "
            f"paired ratio median {statistics.median(ratios):.4f} "
            f"[{low:.4f}, {high:.4f}]"
        )


def guard(work: pathlib.Path, pairs: int) -> None:
    workload_root = work / "workload-root"
    target = workload_root / "benchmarks" / "stream_cost"
    target.mkdir(parents=True, exist_ok=True)
    (workload_root / "benchmarks" / "__init__.py").write_text("", encoding="utf-8")
    (target / "__init__.py").write_text("", encoding="utf-8")
    digest = hashlib.sha256()
    for name in WORKLOAD_FILES:
        content = (pathlib.Path("benchmarks/stream_cost") / name).read_bytes()
        (target / name).write_bytes(content)
        digest.update(name.encode())
        digest.update(content)
    python_version = pathlib.Path(".python-version").read_text("utf-8").strip()
    environments = {
        build: RevisionEnvironment(
            revision=build,
            repo_root=workload_root,
            python_executable=work / f"venv-{build}" / "bin" / "python",
            python_version=python_version,
            workload_digest=digest.hexdigest(),
        )
        for build in BUILDS
    }
    with IsolatedReplicaSet(ResourceLimits(cpus=2.0, memory="1g")) as replica_set:
        for case, profile in product(CASE_NAMES, [p.name for p in PROFILES]):
            paired = measure_paired_case(
                environments["main"],
                environments["cand"],
                replica_set.uri,
                case,
                profile,
                block_pairs=pairs,
            )
            ratios = [
                head / base
                for base, head in zip(
                    paired.base_seconds, paired.head_seconds, strict=True
                )
            ]
            low, high = bootstrap_interval(ratios)
            print(
                f"{case:22s} {profile:8s} "
                f"main {statistics.median(paired.base_seconds):.4f}s "
                f"cand {statistics.median(paired.head_seconds):.4f}s "
                f"ratio {statistics.median(ratios):.4f} [{low:.4f}, {high:.4f}]",
                flush=True,
            )


if __name__ == "__main__":
    {"startup": startup, "guard": guard}[sys.argv[1]](
        pathlib.Path(sys.argv[2]), int(sys.argv[3])
    )
