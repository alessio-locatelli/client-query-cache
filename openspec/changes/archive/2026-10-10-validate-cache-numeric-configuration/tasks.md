# Tasks

## 1. Configuration construction

- [x] 1.1 Apply design.md's type-before-range checks to `CacheCoreConfig.__post_init__` in `_core/manager.py`; extend `tests/core/test_lru_storage.py` with parametrized invalid types for each field and valid equal-budget boundaries. Cover booleans, integer subclasses, integral/fractional floats, NaN, both infinities, strings, null and unrelated objects; verify the cache-core delta's error type and field naming while retaining its valid integer eviction test.
- [x] 1.2 Apply the same construction boundary to `LagCaptureWindowConfig.__post_init__` in `_core/stream_cost.py`; extend `tests/core/test_stream_cost.py` using the input categories from task 1.1 across all three fields, retaining valid zero separation and positive count boundaries. Verify both lag-window delta requirements before telemetry can be allocated.
- [x] 1.3 Update the canonical configuration reference and affected Context7 rules to match both delta specs; verify each documented field type, valid range and error against the constructors, without rewriting unrelated rules.

## 2. Code Quality

- [x] 2.1 Scan the entire file for each edited or added test file, including pre-existing tests, and apply AGENTS.md's Writing Tests guidelines and parametrization; verify the resulting test diff.
- [x] 2.2 Confirm no new code prose if applying with Claude Code — inapplicable to OpenAI Codex; another applying agent must reassess its exemption.
