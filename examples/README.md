# Examples

Each example is a complete program that adds `client-query-cache` to a real library that already stores its data in MongoDB. Writes still go to PyMongo, and the library's reads are served from the cache. Each run prints cache statistics as evidence that repeated reads came from the cache and that a later write invalidated the cached entry, and exits with an error if either did not happen.

## Prerequisites

- A MongoDB 8.0+ replica set. The repository's [`docker-compose.yaml`](https://github.com/alessio-locatelli/client-query-cache/blob/main/docker-compose.yaml) starts one on `localhost:27017`, which the examples use by default. To use another deployment, set `MONGODB_URI` to its connection string.
- [uv](https://docs.astral.sh/uv/). Each example declares its own dependencies, and uv installs them into a separate, cached environment the first time you run it.

Each example deletes its own database when it starts, for example `client_query_cache_example_requests_cache`, so do not point `MONGODB_URI` at a deployment where that database holds data you need.

## Run the examples

Run each command from the [repository checkout](https://github.com/alessio-locatelli/client-query-cache). The filenames below link to executable source; the hosted guides explain the integrations.

| Example                                                                                                                                         | Library                                                                        | Run                                               |
| ----------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ | ------------------------------------------------- |
| [`requests_cache_example.py`](https://github.com/alessio-locatelli/client-query-cache/blob/main/examples/requests_cache_example.py)             | [requests-cache](https://github.com/requests-cache/requests-cache)             | `uv run examples/requests_cache_example.py`       |
| [`celery_example.py`](https://github.com/alessio-locatelli/client-query-cache/blob/main/examples/celery_example.py)                             | [Celery](https://github.com/celery/celery)                                     | `uv run examples/celery_example.py`               |
| [`py_abac_example.py`](https://github.com/alessio-locatelli/client-query-cache/blob/main/examples/py_abac_example.py)                           | [py-abac](https://github.com/ketgo/py-abac)                                    | `uv run examples/py_abac_example.py`              |
| [`aiohttp_client_cache_example.py`](https://github.com/alessio-locatelli/client-query-cache/blob/main/examples/aiohttp_client_cache_example.py) | [aiohttp-client-cache](https://github.com/requests-cache/aiohttp-client-cache) | `uv run examples/aiohttp_client_cache_example.py` |
| [`eve_example.py`](https://github.com/alessio-locatelli/client-query-cache/blob/main/examples/eve_example.py)                                   | [Eve](https://github.com/pyeve/eve)                                            | `uv run examples/eve_example.py`                  |

## Hosted integration guides

- [requests-cache guide](https://alessio-locatelli.github.io/client-query-cache/examples/requests-cache/)
- [Celery guide](https://alessio-locatelli.github.io/client-query-cache/examples/celery/)
- [py-abac guide](https://alessio-locatelli.github.io/client-query-cache/examples/py-abac/)
- [aiohttp-client-cache guide](https://alessio-locatelli.github.io/client-query-cache/examples/aiohttp-client-cache/)
- [Eve guide](https://alessio-locatelli.github.io/client-query-cache/examples/eve/)
