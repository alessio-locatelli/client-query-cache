# Installation

## Requirements

The 0.8 release distribution includes a native module. Binary wheels target CPython 3.14+ on Linux x86-64 with glibc 2.28+. Shared caching additionally requires Linux 5.1+ with `memfd` sealing and `/proc`. Free-threaded interpreters and other platforms are not supported by this release. Source builds require [Rust and Cargo](https://rust-lang.org/tools/install).

- Python 3.14 or newer and PyMongo 4.18.1 or newer, as declared by the package.
- Caching requires MongoDB 8.0+ on a replica set or sharded cluster. Change streams are unavailable on standalone servers; the library also enforces its MongoDB version floor at startup.
- A caller-owned PyMongo client with access to the collections and their database change stream.

On standalone servers and MongoDB versions below 8.0, reads run through PyMongo without caching. The manager logs a warning when it cannot establish a database change stream; see [stream health](../operations/monitoring.md#bypass-reasons-and-stream-health).

## Install

```bash
uv add client-query-cache
```

Or install with pip:

```bash
pip install client-query-cache
```

For optional telemetry, install `client-query-cache[otel]` and follow [Monitoring](../operations/monitoring.md#opentelemetry-metrics).

## Dependency upgrades

Commit your application's lockfile, such as `uv.lock` or `poetry.lock`, and deploy from those selected versions. For pip-based deployments, use a pinned dependency set. See [uv's locking and syncing guidance](https://docs.astral.sh/uv/concepts/projects/sync/) or [Poetry's lockfile guidance](https://python-poetry.org/docs/basic-usage/#committing-your-poetrylock-file-to-version-control).

PyMongo upgrades need application testing: the cache's driver integration can be sensitive to changes between releases, including patch releases. Before deploying an update, exercise cached hits and misses, cursor consumption, session bypass, startup, shutdown, and recovery in your application. A lockfile makes dependency selection reproducible; it does not prove compatibility, and passing CI covers only the behavior your checks exercise.

## Local MongoDB

The repository’s [`docker-compose.yaml`](https://github.com/alessio-locatelli/client-query-cache/blob/main/docker-compose.yaml) provides an example single-member replica set for local development. From a [repository checkout](https://github.com/alessio-locatelli/client-query-cache), run:

```console
docker compose up -d mongo
docker compose run --rm mongo_helper
```

<!-- For --rm: The default is retaining the stopped container. We override it because initialization
should leave no stopped helper ([Compose run](https://docs.docker.com/reference/cli/docker/compose/run/)). -->

The helper initializes the replica set if needed and waits until it is writable. When it exits successfully, the tutorials can connect to `mongodb://localhost:27017`. They write to the `client_query_cache_tutorial` database. This setup is for local evaluation; see [deployment guidance](../operations/deployment.md) for application deployments.

Stop the local services with:

```console
docker compose down
```

See the [official Docker Compose documentation](https://docs.docker.com/compose/) for tool installation and usage.
