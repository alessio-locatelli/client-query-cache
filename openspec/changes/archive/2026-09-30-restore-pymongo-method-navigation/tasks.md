# Tasks

## 1. Explicit cached views

- [x] 1.1 Add `CacheManager.cached(collection)` to `src/client_query_cache/synchronous/manager.py`: accept a typed PyMongo `Collection`, reject a collection whose `database.client is not cache_manager.client` before I/O, and construct a view whose `.raw is collection`; add focused cases in `tests/synchronous/test_manager.py` for raw identity, optioned handles, foreign-client rejection, and multiple safe view constructions without asserting view-object identity.
- [x] 1.2 Add the matching typed accessor to `src/client_query_cache/asynchronous/manager.py` for `AsyncCollection`; cover ownership, `.raw` identity, optioned handles, and multiple safe view constructions in `tests/asynchronous/test_manager.py`.
- [x] 1.3 Add short sync/async accessor examples to `docs/api-reference.md` using `cache_manager` for the `CacheManager` instance and `cached_collection` for its read view; explain that repeated `cached(collection)` calls are safe and share manager state without promising the same view object. Verify that each example uses a real PyMongo collection for writes and the cached view for the six supported reads.

## 2. Remove untyped PyMongo delegation

- [x] 2.1 Replace `CachedCollection.__getattr__` and `_wrap_delegated` in both execution models with typed subcollection traversal only; make declared PyMongo method/property names absent from the cached view raise `AttributeError`. Add typed `CachedCollection.__getitem__` in both models so `cached_collection["insert_one"]` can name a subcollection despite the method-name collision. Update both `test_collection.py` files to cover ordinary and colliding subcollection names, direct raw writes/admin calls, and optioned raw collections passed through `cache_manager.cached(...)`.
- [x] 2.2 Make the equivalent change to both `CachedDatabase` classes; update both `test_database.py` files to cover typed subcollection access, raw `create_collection`/`get_collection`/`with_options`, and the existing indexed cached-read path.
- [x] 2.3 Rewrite the sync/async README quick starts and `docs/api-reference.md` for the current two-handle interface, using `cache_manager` and `cached_collection` in examples and omitting historical migration prose because there are no real users yet. Add one final-behavior entry under `CHANGELOG.md` Unreleased. Correct the existing claim that all cached reads have PyMongo's signatures; verify the examples reflect `find`/`aggregate` list results and the async `find` awaitable.

## 3. Tooling and integration evidence

- [x] 3.1 Add a small typed consumer example using `cache_manager` and `cached_collection` that exercises both sync and async `collection.insert_one`, `collection.drop`, `cached_collection.find_one`, and `cached_collection.raw.find`; verify mypy reports invalid PyMongo arguments and rejects `cached_collection.insert_one(...)`, while a representative IDE language server navigates `collection.insert_one` and `collection.drop` to PyMongo declarations. Record the manual navigation result in the change's implementation notes or commit body; do not claim a tool-independent IDE guarantee from mypy alone.
- [x] 3.2 Update affected integration call sites that currently rely on facade delegation, then verify writes through the raw handle still invalidate cached reads and optioned collections still obey cache eligibility in both execution models. Obtain two views with `cache_manager.cached(collection)` and verify an entry admitted by one can be hit by the other while the database uses one stream supervisor. Compare view-construction and representative cached hit/miss measurements with the pre-change baseline; record the commands and concise measurements in the commit body, leaving raw benchmark output untracked.
- [x] 3.3 Revisit the `requests-cache` `MongoDict` consumer shape described in `design.md` with the implemented API: confirm a retained PyMongo collection handles `replace_one`, `find_one_and_delete`, `delete_many`, `index_information`, `create_index`, `drop_index`, and `drop` while a view handles `find_one`, `find`, and `estimated_document_count`, and that repeated view retrieval would not duplicate streams. Record the result in the commit body; do not modify the other repository or present its caller-closing `MongoDict.close()` behavior as compatible with a shared client.

## 4. Code Quality

- [x] 4.1 Scan the entire file for every edited or added test, including pre-existing tests, and apply the `AGENTS.md` Writing Tests guidelines (including parametrization); verify the resulting tests exercise behavior rather than helper internals.
- [x] 4.2 Confirm that no new prose was added to code by Claude Code.
