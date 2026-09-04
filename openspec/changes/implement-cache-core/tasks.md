## 1. Define manager primitives

- [ ] 1.1 Implement driver-neutral manager contracts, lifecycle states, cache errors, request canonicalization, and identity declarations; verify focused unit tests reject unsupported admissions.
- [ ] 1.2 Implement document and derived-result identity records with namespace generation guards; verify generation comparison and cache insertion are serialized with invalidation and lookups reject older-generation entries.

## 2. Add bounded BSON storage

- [ ] 2.1 Implement the configurable shared weighted BSON LRU with the 64 MiB default and 1 MiB maximum entry; verify eviction, oversize rejection, and shared-budget tests.
- [ ] 2.2 Implement aliases, namespace clearing, and BSON encode/decode value isolation; verify a caller mutation cannot change a later hit.

## 3. Add safe inspection

- [ ] 3.1 Implement immutable capacity, lifecycle, hit/miss, eviction, and bypass snapshots with safe structured logs; verify no snapshot or log includes a document, query, credential, or resume token.
