# Installation

## Requirements

- Python 3.14.6 or newer and PyMongo 4.18.1 or newer, as declared by the package.
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
