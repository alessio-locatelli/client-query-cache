## 1. Separate test tiers

- [ ] 1.1 Register strict unit, integration, end-to-end, and benchmark pytest markers and commands; verify the unit command does not construct a MongoDB client.
- [ ] 1.2 Reclassify existing tests and remove fixed `localhost:27017` assumptions; verify unit tests run without a container runtime.

## 2. Create isolated database tests

- [ ] 2.1 Add a Testcontainers single-node replica-set fixture with primary-election readiness, dynamic endpoints, and cleanup; verify an integration test uses it for an independent raw write.
- [ ] 2.2 Add clean-wheel end-to-end harness support and Docker/Podman preflight guidance; verify it uses the installed public package and never contacts a user database.

## 3. Enforce complete production coverage

- [ ] 3.1 Configure combined production branch coverage with a 100 percent threshold and actionable XML/text reports; verify an intentionally uncovered reachable branch fails.
- [ ] 3.2 Add deterministic tests or remove dead code until coverage reports 100 percent without hiding ordinary paths; verify the complete coverage command succeeds.
