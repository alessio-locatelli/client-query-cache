import importlib
import json
import pathlib
import pkgutil
import re
import sys
import time

BANNED = (
    "WeightedLru",
    "LockOrderGuard",
    "NamespaceLock",
    "CacheStatistics",
    "IdentityCacheKey",
    "NamespaceCacheKey",
    "ByteRelay",
    "EchoOwner",
    "duplicate_tcp",
    "echo_roundtrip",
    "_ownership",
    "_recency",
    "_probes",
    "admit_identity_encoded",
    "lose_history",
    "_reference_canonicalize",
)
OPTIONAL_MODULES = ("client_query_cache.otel",)
BANNED_MODULES = (
    "_core.manager",
    "_core.lru",
    "_core.namespace",
    "_core.retention",
    "_core.locking",
    "_core.lifecycle",
)


def audit() -> None:
    package_module = importlib.import_module("client_query_cache")
    extension = importlib.import_module("client_query_cache._shared_index")
    package = pathlib.Path(package_module.__file__ or "").parent
    files = [
        path
        for path in package.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    ]
    modules = sorted(
        module.name
        for module in pkgutil.walk_packages([str(package)], "client_query_cache.")
    )
    failed = []
    for name in modules:
        try:
            importlib.import_module(name)
        except ImportError as error:
            failed.append((name, str(error)))
    loaded_engine = [
        name
        for name in sys.modules
        if any(name.endswith(banned) for banned in BANNED_MODULES)
    ]
    exports = {}
    for name in dir(extension):
        if name.startswith("__"):
            continue
        attribute = getattr(extension, name)
        exports[name] = (
            len([a for a in dir(attribute) if not a.startswith("__")])
            if isinstance(attribute, type)
            else "function"
        )
    leaked_exports = sorted(
        {
            name
            for name in BANNED
            if hasattr(extension, name)
            or any(
                hasattr(attribute, name)
                for attribute in vars(extension).values()
                if isinstance(attribute, type)
            )
        }
    )
    banned_hits: dict[str, list[str]] = {}
    for path in files:
        content = path.read_bytes()
        for banned in BANNED:
            pattern = (
                rb"(?<![A-Za-z0-9_])"
                + re.escape(banned.encode())
                + rb"(?![A-Za-z0-9_])"
            )
            if re.search(pattern, content):
                banned_hits.setdefault(str(path.relative_to(package)), []).append(
                    banned
                )
    unexpected_failures = [
        failure for failure in failed if failure[0] not in OPTIONAL_MODULES
    ]
    print(
        json.dumps(
            {
                "package": str(package),
                "file_count": len(files),
                "modules": len(modules),
                "import_failures": failed,
                "engine_modules_loaded": loaded_engine,
                "extension_exports": exports,
                "leaked_exports": leaked_exports,
                "banned_name_hits": banned_hits,
                "so_bytes": (package / "_shared_index.abi3.so").stat().st_size,
            },
            indent=1,
        )
    )
    if unexpected_failures or loaded_engine or leaked_exports or banned_hits:
        raise SystemExit(1)


def resident_kib() -> int:
    with pathlib.Path("/proc/self/status").open(encoding="ascii") as status:
        for line in status:
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    raise SystemExit("VmRSS is missing")


def startup_child() -> None:
    cpu_before = time.process_time()
    wall_before = time.perf_counter()
    rss_before = resident_kib()  # pytriage: TR11 - baseline sampled before later phases
    package = importlib.import_module("client_query_cache")
    wall_import = time.perf_counter()
    rss_import = resident_kib()  # pytriage: TR11 - baseline sampled before later phases
    pymongo = importlib.import_module("pymongo")
    client = pymongo.MongoClient(connect=False)
    manager = package.CacheManager(client)
    wall_manager = time.perf_counter()
    rss_manager = resident_kib()
    manager.close()
    client.close()
    importlib.import_module("client_query_cache.shared")
    wall_shared = time.perf_counter()
    rss_shared = resident_kib()
    print(
        json.dumps(
            {
                "import_seconds": wall_import - wall_before,
                "manager_seconds": wall_manager - wall_import,
                "shared_import_seconds": wall_shared - wall_manager,
                "cpu_seconds": time.process_time() - cpu_before,
                "rss_baseline_kib": rss_before,
                "rss_import_kib": rss_import,
                "rss_manager_kib": rss_manager,
                "rss_shared_kib": rss_shared,
            }
        )
    )


if __name__ == "__main__":
    {"audit": audit, "startup-child": startup_child}[sys.argv[1]]()
