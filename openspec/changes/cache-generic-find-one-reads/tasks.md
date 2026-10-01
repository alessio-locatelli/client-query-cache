# Tasks

## 1. Generic single-document caching

- [ ] 1.1 Add shared pure query/shape normalization for deterministic mapping `find_one` reads, preserving scalar-ID shorthand and exact `_id` behavior. Add native sync/async namespace lookup/capture/read/admission paths using the existing core and a distinct discriminator tag per design D1. Replace `test_find_one_with_a_non_id_filter_bypasses_cache` with parametrized positive/negative/compound/match-all behavior tests in both collection test modules; verify repeated reads hit, extra predicates are retained, returned mutations are isolated, and only one database read occurs on an eligible miss.
- [ ] 1.2 Exercise generic invalidation for writes to matching and nonmatching documents, inserts after negative admission, drop/recreate, unavailable index metadata with otherwise valid eligibility, and reads spanning invalidation/recovery. Extend existing real-server sync/async tests and operation-ordering invariants rather than mocking an impossible cache state. Verify original unsafe/filter/projection/profile/session/key bypass behavior and driver errors remain intact. Update generic `find_one` eligibility and eventual-consistency guidance in the API reference/README in this part.

## 2. Explicit sort and collation

- [ ] 2.1 Add keyword-only sort/collation parameters to both `find_one` variants and propagate them through all direct/miss paths. Extend effective-collation unique matching and read shapes per design D2; use namespace guards for every non-simple effective `_id` collation, including inherited defaults and scalar-ID shorthand. Add parametrized sync/async cases for different first-document sorts, inherited non-simple matching with a stored string ID of different spelling followed by its invalidation, explicit simple overrides, explicit and inherited matching/mismatching unique-index collations, sort-dependent projected metadata, differing projections/codecs, and partial/sparse/hashed generic fallback. In particular, verify that omitting per-query collation retains the unique-key optimization when the collection default matches the index. Verify identity, unique-key and generic keys cannot cross incompatible shapes and aliases remain honest.
- [ ] 2.2 Validate supported option shapes before a hit or route invalid/unsupported shapes to PyMongo. Warm valid entries, then issue malformed sort/collation/projection/filter requests and unknown kwargs; verify the original driver errors or direct execution are preserved. Keep validation limited to publicly supported shapes, without reproducing server query evaluation. Update method signatures, sort/collation examples and one Unreleased entry to describe implemented behavior only; verify public type checking and documented calls.

## 3. Resource evidence

- [ ] 3.1 Compare direct and cached compound/sorted/collated `find_one`, negative hits, and write-heavy invalidation with the pre-change identity-hit baseline after cheap checks pass. Record commands, round trips, latency, allocations, hit rate and the observed bottleneck in the implementation commit body. Verify no new per-hit index discovery/network request and no raw results are tracked.

## 4. Code Quality

- [ ] 4.1 Scan the entire file for each edited or added test, including pre-existing tests, and apply the AGENTS.md Writing Tests rules, especially parametrization and fixtures for cleanup. Verify no helper-only coverage tests or synthetic impossible scenarios were introduced.
- [x] 4.2 If you are Claude Code, confirm that no new prose was added to code; OpenAI Codex is exempt. Not applicable: these planning artifacts were authored by Codex.
