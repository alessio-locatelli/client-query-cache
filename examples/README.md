# Examples

Start with one of the FastAPI applications:

- [Shared workers](https://alessio-locatelli.github.io/client-query-cache/examples/fastapi-shared/): real Granian HTTP processes reuse `_id` documents and one owner stream. The self-check proves the second worker's first read hits without a MongoDB query, verifies invalidation, and checks graceful shutdown.
- [Compact process-local application](https://alessio-locatelli.github.io/client-query-cache/examples/fastapi-minimal/): one client and `CacheManager` per lifespan, cached GETs, direct PATCH responses and diagnostics.
- [Process-local catalogue](https://alessio-locatelli.github.io/client-query-cache/examples/fastapi/): tenant filtering, bounded pages and a deployment cache flag. `--serve` runs independent caches under Uvicorn.

The remaining adapters use process-local caching for MongoDB-backed libraries. Every program checks reuse and invalidation and fails if its expected evidence is absent. Most self-checks use in-process HTTP clients; the shared-worker check opens actual network connections. See [manager selection](https://alessio-locatelli.github.io/client-query-cache/getting-started/choose-a-manager/) before adapting an integration.

Authorization policies and Celery task state can lag a write until invalidation arrives. Do not use these examples to infer immediate freshness; see [consistency limits](https://alessio-locatelli.github.io/client-query-cache/usage/consistency/).

## Prerequisites

- A disposable MongoDB deployment meeting the [database requirements](https://alessio-locatelli.github.io/client-query-cache/getting-started/installation/#requirements). The repository's [`docker-compose.yaml`](https://github.com/alessio-locatelli/client-query-cache/blob/main/docker-compose.yaml) starts one on `localhost:27017`, which the examples use by default. To use another deployment, set `MONGODB_URI` to its connection string.
- A host meeting the [platform requirements](https://alessio-locatelli.github.io/client-query-cache/getting-started/installation/#requirements), including the additional requirements for shared caching.
- [uv](https://docs.astral.sh/uv/). Each example declares its own dependencies, and uv installs them into a separate, cached environment the first time you run it.

Self-checks reset their dedicated database, for example `client_query_cache_example_requests_cache`. Use a disposable deployment without valuable data under the `client_query_cache_example_` prefix. Web `--serve` modes leave existing data intact. Keep connection credentials in your normal secret configuration and do not print the URI.

## Run the examples

Run each command from the [repository checkout](https://github.com/alessio-locatelli/client-query-cache). The filenames below link to executable source; the hosted guides explain the integrations.

| Example                                                                                                                                         | Library or framework                                                           | Run                                               |
| ----------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ | ------------------------------------------------- |
| [`fastapi_shared_example.py`](https://github.com/alessio-locatelli/client-query-cache/blob/main/examples/fastapi_shared_example.py)             | FastAPI + [Granian](https://github.com/emmett-framework/granian)               | `uv run examples/fastapi_shared_example.py`       |
| [`requests_cache_example.py`](https://github.com/alessio-locatelli/client-query-cache/blob/main/examples/requests_cache_example.py)             | [requests-cache](https://github.com/requests-cache/requests-cache)             | `uv run examples/requests_cache_example.py`       |
| [`fastapi_catalogue_example.py`](https://github.com/alessio-locatelli/client-query-cache/blob/main/examples/fastapi_catalogue_example.py)       | [FastAPI](https://fastapi.tiangolo.com/)                                       | `uv run examples/fastapi_catalogue_example.py`    |
| [`fastapi_minimal_example.py`](https://github.com/alessio-locatelli/client-query-cache/blob/main/examples/fastapi_minimal_example.py)           | [FastAPI](https://fastapi.tiangolo.com/)                                       | `uv run examples/fastapi_minimal_example.py`      |
| [`celery_example.py`](https://github.com/alessio-locatelli/client-query-cache/blob/main/examples/celery_example.py)                             | [Celery](https://github.com/celery/celery)                                     | `uv run examples/celery_example.py`               |
| [`py_abac_example.py`](https://github.com/alessio-locatelli/client-query-cache/blob/main/examples/py_abac_example.py)                           | [py-abac](https://github.com/ketgo/py-abac)                                    | `uv run examples/py_abac_example.py`              |
| [`aiohttp_client_cache_example.py`](https://github.com/alessio-locatelli/client-query-cache/blob/main/examples/aiohttp_client_cache_example.py) | [aiohttp-client-cache](https://github.com/requests-cache/aiohttp-client-cache) | `uv run examples/aiohttp_client_cache_example.py` |
| [`eve_example.py`](https://github.com/alessio-locatelli/client-query-cache/blob/main/examples/eve_example.py)                                   | [Eve](https://github.com/pyeve/eve)                                            | `uv run examples/eve_example.py`                  |

Run all executable self-checks with `just examples`; the shared self-check also verifies its `--serve` launcher.

## Hosted integration guides

- [FastAPI shared-worker guide](https://alessio-locatelli.github.io/client-query-cache/examples/fastapi-shared/)

- [requests-cache guide](https://alessio-locatelli.github.io/client-query-cache/examples/requests-cache/)
- [FastAPI catalogue guide](https://alessio-locatelli.github.io/client-query-cache/examples/fastapi/)
- [Compact FastAPI guide](https://alessio-locatelli.github.io/client-query-cache/examples/fastapi-minimal/)
- [Celery guide](https://alessio-locatelli.github.io/client-query-cache/examples/celery/)
- [py-abac guide](https://alessio-locatelli.github.io/client-query-cache/examples/py-abac/)
- [aiohttp-client-cache guide](https://alessio-locatelli.github.io/client-query-cache/examples/aiohttp-client-cache/)
- [Eve guide](https://alessio-locatelli.github.io/client-query-cache/examples/eve/)
