# Tasks

## 1. Installed runtime

- [x] 1.1 Move reusable owner, attachment, index, wire and adapter code to the library; update research callers and retain existing behavior coverage.
- [x] 1.2 Implement validated public configuration and spawned server ownership, connection transfer, bounded shutdown/restart and secure attachment; exercise lifecycle and unauthorized peer cases.
- [x] 1.3 Export sync/async shared managers with context management, closed/fork checks, native bypass for unsupported reads and cancellation-safe cleanup; cover public reads against MongoDB.
- [x] 1.4 Bypass explicit non-simple collation before inherited caching; cover dictionary and Collation inputs in both worker APIs.
- [x] 1.5 Start replacement workers in direct-read mode during owner loss, retry local attachment after recovery, and preserve explicit credential/configuration and persistent-access failures.
- [x] 1.6 Reject retention of oversized encoded/decoded keys while preserving small-key reuse; cover repeated large identifiers.

## 2. Distribution and deployment

- [x] 2.1 Bundle Rust with the Python distribution at 0.8.0, build a portable Linux wheel and source artifact, and exercise installed native startup outside the checkout.
- [x] 2.2 Update release workflows, deployment/API guides, README, Context7 and changelog together; verify the documented worker pattern.

## 3. Delivery evidence

- [x] 3.1 Add a reproducible public-API benchmark and concise measured report covering sync/async four-worker hot/cold reads, resource costs and observed bottlenecks.
- [x] 3.2 Revise parent issue #279 to retain ownership through integrated release readiness and link the delivery artifacts without closing it.

## 4. Code Quality

- [x] 4.1 Scan the entire file for edited or added tests and apply AGENTS.md test guidance, including parametrization.
- [x] 4.2 Claude-only prose restriction does not apply; implemented by OpenAI Codex.
