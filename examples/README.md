# Examples

Each example is a complete program that adds `client-query-cache` to a real library that already stores its data in MongoDB. Writes still go to PyMongo, and the library's reads are served from the cache. Each run prints cache statistics as evidence that repeated reads came from the cache and that a later write invalidated the cached entry, and exits with an error if either did not happen.

## Prerequisites

- A MongoDB 8.0+ replica set. The repository's [`docker-compose.yaml`](../docker-compose.yaml) starts one on `localhost:27017`, which the examples use by default. To use another deployment, set `MONGODB_URI` to its connection string.
- [uv](https://docs.astral.sh/uv/). Each example declares its own dependencies, and uv installs them into a separate, cached environment the first time you run it.

Each example deletes its own database when it starts, for example `client_query_cache_example_requests_cache`, so do not point `MONGODB_URI` at a deployment where that database holds data you need.

## Examples

Run each command from the repository root.

| Example                                                  | Library                                                            | Run                                         |
| -------------------------------------------------------- | ------------------------------------------------------------------ | ------------------------------------------- |
| [`requests_cache_example.py`](requests_cache_example.py) | [requests-cache](https://github.com/requests-cache/requests-cache) | `uv run examples/requests_cache_example.py` |
