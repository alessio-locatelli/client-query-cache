## 1. Separate test tiers

- [x] 1.1 Register strict unit, integration, end-to-end, and benchmark pytest markers and commands; verify the unit command does not construct a MongoDB client.
- [x] 1.2 Reclassify existing tests and remove fixed `localhost:27017` assumptions; verify unit tests run without a container runtime.

## 2. Create isolated database tests

- [x] 2.1 Add a Testcontainers single-node replica-set fixture with primary-election readiness, dynamic endpoints, and cleanup; verify an integration test uses it for an independent raw write.
- [x] 2.2 Add clean-wheel end-to-end harness support and Docker/Podman preflight guidance; verify it uses the installed public package and never contacts a user database.

## 3. Enforce the production coverage baseline

- [x] 3.1 Configure combined production branch coverage with the measured 81.10 percent threshold and actionable XML/text reports; verify an intentionally uncovered reachable branch fails the gate.
- [x] 3.2 Keep every importable production module in measurement without coverage exclusions, assign the 100 percent threshold to `implement-change-stream-coherency`, and verify the complete coverage command succeeds at the recorded baseline.
