## 1. Document the public interface

- [ ] 1.1 Replace the proof-of-concept README with verified audience, topology prerequisites, installation, sync/async quick starts, lifecycle, consistency, and non-goal guidance; verify every sample against the public API.
- [ ] 1.2 Publish the API reference and prototype migration guide; verify it covers configuration, limits, ownership, raw fallback, and rollback to PyMongo collections.

## 2. Document architecture and operations

- [ ] 2.1 Add system requirements, capacity estimation, HLD/LLD, retry/error, observability, security, connection-pool, and recovery guidance; verify internal and external references resolve.
- [ ] 2.2 Add workload-selection and performance guidance linked to the retained reports from `benchmark-change-stream-costs`; verify it makes no universal or unsupported performance claim.

## 3. Verify public documentation

- [ ] 3.1 Run all documented commands and examples in a clean supported environment, correct any mismatch, and record the exact validation evidence.
