# Installation

## Requirements

| Component         | Supported configuration                                                                                                                  |
| ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Python            | Standard CPython 3.14+; free-threaded builds are unsupported                                                                             |
| PyMongo           | 4.18.1 or newer                                                                                                                          |
| Package platform  | Linux x86-64 or ARM64 with glibc 2.28+; other platforms are unsupported                                                                  |
| Shared-cache host | Linux 5.1+ with `memfd` sealing and `/proc` available                                                                                    |
| MongoDB caching   | MongoDB 8.0+ on a replica set or sharded cluster                                                                                         |
| Database access   | Collection reads and metadata (`listCollections`, plus `listIndexes` for unique-key discovery), and database-level `changeStream` access |

Binary wheels include the Rust native module. Source builds require [Rust and Cargo](https://rust-lang.org/tools/install).

For shared caching, also review the [owner and worker security requirements](../operations/shared-cache.md#security-and-monitoring).

On reachable standalone MongoDB servers or versions below the minimum, reads run through PyMongo without caching. The manager logs a warning when it cannot establish a database change stream; see [stream health](../operations/monitoring.md#bypass-reasons-and-stream-health). Uncached reads still require a reachable server that can serve the operation; a missing server can raise PyMongo's `ServerSelectionTimeoutError`.

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

Deploy from a lockfile or pinned dependency set; see [uv locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/) or [Poetry's lockfile guidance](https://python-poetry.org/docs/basic-usage/#committing-your-poetrylock-file-to-version-control).

Test PyMongo upgrades, including patch releases, against your application's cached hits, misses, cursor consumption, session bypass, startup, shutdown and recovery. The integration depends on driver behavior beyond query signatures.

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

For disposable test databases in GitLab CI or GitHub Actions, see [MongoDB in CI](mongodb-ci.md).
