# Design

## Context

See proposal.md - Why. `tests/conftest.py`'s `make_fake_document(faker)` fixture already produces a MongoDB-compatible document (BSON-safe types, `_id` forced to `str(uuid.uuid4())`) and is already used throughout `tests/synchronous/test_collection.py` and `tests/asynchronous/test_collection.py`. The same directories also contain `test_unique_key_reads.py` and `test_streams_integration.py` (both `pytest.mark.integration`, real MongoDB via testcontainers), which instead hand-roll literals like `{"_id": "doc-1", "email": "a@example.com", "name": "Ada"}` repeated near-verbatim across roughly ten tests each, without using the fixture that already sits next to them.

## Goals / Non-Goals

**Goals:**

- Replace incidental literals in the two identified integration-test files (sync and async) with `faker`-generated values, reusing `make_fake_document` where a full document is needed and direct `faker` calls where only a single field (e.g. an email) is needed.
- Add a name, constant, or comment to the handful of significant fixed values identified as currently undocumented, without touching values whose git history already explains them.
- Document the convention once in `AGENTS.md` so it applies going forward without a repeat audit.

**Non-Goals:**

- `tests/core/*` - the report found values there are either already self-documenting (`"fresh"`/`"stale"`, `"a"`/`"b"`) or trivial placeholders (`[1, 2, 3]` as opaque cached content) where a fixed literal communicates the test at least as well as a generated one; this mirrors the precedent already set for `test_canonical.py`/`test_order_sensitive_keys.py`/`test_projection.py`/`test_unique_keys.py`/`test_lru.py` in the prior `add-hypothesis-property-tests` change, where fixed examples were kept as the more readable choice.
- `tests/benchmark/stream_cost/*` - already has its own descriptive defaults-factory convention (`_identity(**overrides)`/`_environment(**overrides)` in `test_config.py`) for "don't-care" structured config; migrating it to `faker` would be a lateral move with no readability gain.
- `tests/e2e/test_installed_package.py` - its one incidental literal lives inside a string executed by `subprocess.run` in a clean venv with no access to the outer test's `faker` fixture; the new "no `faker` access" requirement in the spec delta explicitly keeps this as a fixed value rather than justifying cross-process plumbing for a single value.
- A repo-wide mechanical sweep for every hard-coded literal in every test file. The proposal targets the two files the audit found to have the highest concentration of incidental, repeated literals; the documented convention (not a one-time sweep) is what prevents recurrence elsewhere.

## Decisions

**Migrate `test_unique_key_reads.py` and `test_streams_integration.py` (sync and async) using existing fixtures/helpers, not a new generic "arbitrary value" fixture.** `make_fake_document(faker)` already exists for full documents; a single generated email or `_id` needed on its own uses the `faker` fixture directly (`faker.email()`, `faker.uuid4()`) inside the test body as a local variable, matching how `faker` is already consumed elsewhere in the suite. No new shared fixture is introduced for "some filter" or "some count," since the audit found no repeated need for one beyond documents and emails.

**Reuse a single generated value across a test's write and its later read/assertion.** Several tests filter by the same field they just inserted (e.g. `collection.find_one({"email": <value>})` after inserting a document with that email) or assert a projected/returned field equals what was inserted (e.g. `assert first == {"name": "Ada"}`). The migration keeps this by binding the generated value to a local variable once per test and referencing that variable everywhere the same value is needed, per the spec delta's reuse requirement - never calling `faker.email()` a second time expecting the same result.

**Preserve distinct before/after pairs explicitly.** `test_streams_integration.py`'s `{"$set": {"v": 2}}`-style updates depend on the new value differing from the original so the invalidation assertion is meaningful. The migration generates the "before" value from `faker` and derives a distinct "after" value from it (e.g. a second `faker` call, retried or offset until it differs) rather than two independent calls that could coincidentally match.

**Document the significant-value cases with a comment rather than extracting a named constant, where extraction would add indirection for a single use site.** `test_admission_contracts.py`'s stress-test tuning (`8` workers, `50` iterations, `% 5`, `% 10 == 0`) and `test_collection.py`'s `tight_budget_cache_manager` (`shared_budget_bytes=200, max_entry_bytes=50`) are each used at a single call site; a short inline comment explaining what the number controls and, for the budget fixture, its relationship to the fake documents it's meant to admit or reject, satisfies the spec delta's "descriptive name, constant, fixture, or comment" requirement without introducing a constant only one line references.

**Verify MongoDB-safe generation with existing typed Faker providers.** Per the audit's risk note, migrated `_id`/email/name values use `faker.uuid4()`/`faker.email()`/`faker.first_name()`-style typed providers (as `make_fake_document` already does for `_id`) rather than free-form `faker.pystr()`, avoiding characters MongoDB disallows in identifiers.

## Risks / Trade-offs

- [A generated "after" value could coincidentally equal the "before" value, silently weakening an invalidation assertion] → Derive the after-value deterministically from the before-value (e.g. `before + 1` for an integer field) rather than drawing two independent Faker values, so the pair's distinctness doesn't depend on generator luck.
- [Migrating `test_unique_key_reads.py` touches ~10 tests per sync/async file; a mechanical mistake in one could silently loosen an assertion (e.g. comparing a variable to itself instead of to the inserted value)] → Each migrated test keeps its existing assertion shape (`assert first == {"name": <generated_name>}`) and is run individually after the change, not just as part of the full suite, to catch a tautological assertion introduced by mistake.
- [Faker's default locale/config could occasionally generate an email or name containing characters that interact oddly with MongoDB collation or unique-index tests] → Use the same typed providers `make_fake_document` already relies on, which the existing integration suite has run against real MongoDB without incident.
