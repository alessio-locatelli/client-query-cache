# Tasks

## 1. Core library handlers

- [ ] 1.1 `src/client_query_cache/_core/find_one_reads.py:61` (`Collation(**document)`: `TypeError, ValueError`): read `pymongo.collation.Collation.__init__` and determine which of the two it raises for `document` keys limited to `_COLLATION_FIELDS`. Delete each type that no input raises; split the survivors into one clause per type. Verify with `git grep -n 'Collation(\*\*document)' -A3 src` and a parametrized test in the existing `find_one_reads` tests that raises each surviving type.
- [ ] 1.2 `src/client_query_cache/_core/manager.py:478,601,679` and `src/client_query_cache/_core/projection.py:32` (`BSONError, OverflowError` around `encode_value` / `bson.encode`): reproduce under `/tmp/agents/split-except/` with a value that overflows BSON integers and with a value `bson` rejects (for example a `set`), and record which of `BSONError` and `OverflowError` each raises. Remove unreachable types; split survivors into one clause each, returning the same `AdmissionOutcome.DECLINED_UNENCODABLE` / `stripped` value as today. Verify a test per surviving type exists for each of the four sites (parametrize over input), and `just pytest tests -k "unencodable or projection"` passes.

## 2. Change-stream handlers (async and sync in lockstep)

- [ ] 2.1 `src/client_query_cache/{asynchronous,synchronous}/streams.py` `_run` (`StopAsyncIteration`/`StopIteration, PyMongoError` around `self._stream.next()`): confirm from PyMongo's `ChangeStream.next` source that both end-of-stream and `PyMongoError` are reachable. Keep both, as separate clauses calling `_handle_stream_failure()`. Verify with a test for each type in `tests/asynchronous/` and `tests/synchronous/`.
- [ ] 2.2 Same files, `_record_logical_event_bytes` (`BSONError, TypeError, ValueError` around `bson.encode(dict(event), ...)`): determine which types `bson.encode` raises for an event mapping built from server data and a custom `codec_options`. Delete unreachable types and split the survivors. Verify a test per surviving type in both test packages.

## 3. Benchmark handlers

- [ ] 3.1 `benchmarks/stream_cost/await_configuration.py:95` (`KeyError, TypeError, ValueError` around `expand_await_configuration(json.loads(content))`), `compression_report.py:346` and `report.py:163` (`TypeError, ValueError` around `json.dumps(report, allow_nan=False)`): determine which types each call raises. `json.dumps(..., allow_nan=False)` raises `ValueError` for NaN/inf and `TypeError` for non-serializable values; keep both only if the existing tests exercise both. Delete unreachable types; split survivors, sharing the message construction through a helper if more than one line is duplicated. Verify with a parametrized test per surviving type in the matching `tests/benchmark/` test module.
- [ ] 3.2 `benchmarks/stream_cost/await_run.py:450,559` (`BenchmarkSetupError, PyMongoError, TimeoutError`), `calibration.py:357` (`BenchmarkConfigurationError, PyMongoError`) and `guard_report.py:73` (`BenchmarkSetupError, ValueError`): determine which types the guarded calls can raise. Keep the existing `isinstance(error, BenchmarkSetupError)` dispatch in `await_run.py` only if the other branch is still reachable and tested; otherwise split. Verify a test reaches every surviving type at each site.
- [ ] 3.3 `benchmarks/stream_cost/topology.py:116,153,235` (`DockerException, ContainerStartException`, plus `KeyError, TypeError, ValueError, OverflowError` at `:235`): read `testcontainers` and `docker` sources to establish whether `ContainerStartException` subclasses `DockerException` (if so the pair is redundant: delete the subclass) and which of `KeyError, TypeError, ValueError, OverflowError` `_parse_cpu_usage_nanoseconds` can raise for the Docker stats payload. Delete unreachable types; split survivors. Verify with tests that feed a stats payload triggering each surviving type.

## 4. Test-code handlers

- [ ] 4.1 `tests/asynchronous/test_collection.py:1947` and `tests/synchronous/test_collection.py:1896` (`TypeError, ValueError, OperationFailure`) and `tests/benchmark/real_server/atlas_bandwidth.py:202` (`OSError, RuntimeError, ValueError, DNSException`): run the differential test and the Atlas helper's tests with a temporary `print(type(error))` per clause under `/tmp/agents/` (do not commit it) to find which types occur. Remove types never raised by any parametrized case; if a type is plausible but unexercised, add a parametrized case instead of keeping dead handling. Verify `just pytest tests/asynchronous/test_collection.py tests/synchronous/test_collection.py` passes with no `# pragma: no cover` added.

## 5. Replace `contextlib.suppress`

- [ ] 5.1 In `ruff.toml`, add `[lint.flake8-tidy-imports.banned-api]` with `"contextlib.suppress".msg = "..."` and add `"suppressible-exception"` to `ignore`. Verify `ruff check --select TID251 .` reports only the existing `suppress` uses and imports, and `ruff check --select SIM105 .` is silent.
- [ ] 5.2 `src/client_query_cache/asynchronous/streams.py` (lines ~103, 108, 122, 171, 174) and `src/client_query_cache/synchronous/streams.py` (lines ~109, 166, 169): rewrite each as `try: ... except <Type>: pass`, and keep it only if a test raises `<Type>` there (stream `close()` raising `PyMongoError`; `await task` raising `CancelledError`). Add a parametrized test in `tests/asynchronous/test_streams.py` and `tests/synchronous/test_streams.py` for each reachable site, and delete the `try` for each unreachable one. Verify no missed lines in these modules under `just tests_and_coverage`.
- [ ] 5.3 `benchmarks/stream_cost/proxy.py` (lines 93, 95, 185; `OSError` from socket teardown calls) and `benchmarks/stream_cost/topology.py` (lines 118, 134; `DockerException, ContainerStartException` from `container.stop()`): same procedure as 5.2. For `topology.py`, apply the type audit of task 3.3 first, then use one clause per surviving type. Verify with a test whose fake raises each surviving type.
- [ ] 5.4 `tests/asynchronous/test_streams.py:1105` (`suppress(asyncio.CancelledError)`) and `tests/synchronous/test_streams.py:329` (`suppress(StreamLifecycleError)`): remove the `from contextlib import suppress` import and rewrite with `try`/`except`, or with `pytest.raises` when the exception is always raised. Verify `git grep -nE 'suppress\(|import suppress' -- '*.py'` returns nothing.

## 6. Guidelines and discovery check

- [ ] 6.1 Add two bullets to `AGENTS.md` under "Development Guidelines / General", beside the `get()` bullet: (a) an `except` clause names one exception type; list several only when each is demonstrably raised by the guarded code and covered by a test, otherwise delete it; (b) never use `contextlib.suppress`, because coverage cannot show that its exception is never raised; use `try`/`except` instead. Verify `git diff -- AGENTS.md` shows only those bullets.
- [ ] 6.2 Re-run the two discovery commands from `design.md`:

  ```bash
  git grep -En '^[[:space:]]*except[[:space:]]+(\([[:space:]]*)?[A-Za-z_][A-Za-z0-9_.]*[[:space:]]*,[[:space:]]*[A-Za-z_][A-Za-z0-9_.]*'
  git ls-files -z '*.py' | xargs -0 rg -nUP 'except\s*\(\s*[A-Za-z_][\w.]*\s*,\s*[A-Za-z_][\w.]*'
  ```

  Every remaining hit must be an `isinstance`-dispatch clause whose each branch is covered; verify with `just lint` and `just tests_and_coverage` reaching 100% with no new pragmas. If any audited type turned out to be an upstream defect or an undocumented exception, document it under `docs/` with a tracking-ticket URL (ask the user to file one if none exists).

## 7. Code Quality

- [ ] 7.1 Scan the entire file for edited or added tests (including pre-existing tests within the file) and ensure that the "Writing Tests" guidelines from `AGENTS.md` are applied, including test parametrization.
- [ ] 7.2 If you are Claude Code, confirm that you added no new prose to the code (all "why" explanations must go in the specs and commit bodies). OpenAI Codex is exempt from this rule because it understands the difference between garbage and valuable code comments.
