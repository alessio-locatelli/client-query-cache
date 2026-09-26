import importlib

for module_name in (
    "client_query_cache",
    "client_query_cache.synchronous",
    "client_query_cache.asynchronous",
):
    module = importlib.import_module(module_name)
    for name in module.__all__:
        getattr(module, name)
