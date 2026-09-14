## 1. Raise the minimum server version

- [ ] 1.1 Update `MINIMUM_SERVER_VERSION` and the startup error message in `src/mongo_client_cache/synchronous/streams.py` and `src/mongo_client_cache/asynchronous/streams.py` from 6.0 to 8.0
- [ ] 1.2 Verify the existing below-minimum-version test case in `tests/synchronous/test_streams.py` and `tests/asynchronous/test_streams.py` still passes against the new threshold
- [ ] 1.3 Document the minimum supported MongoDB server version in `README.md`

## 2. Code Quality

- [ ] 2.1 Scan the entire file for edited or added tests (including pre-existing tests within the file) and ensure that the "Writing Tests" guidelines from `AGENTS.md` are applied, including test parametrization.
