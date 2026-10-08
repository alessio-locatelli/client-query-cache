# Tasks

## 1. Correct and focus public guidance

- [ ] 1.1 Apply design.md's method-table decision in `docs/user/reference/api.md`, replacing its contradictory async introduction; verify all six table rows against both collection implementations and cursor tests, and cross-check the existing asyncio tutorial and Context7 wording.
- [ ] 1.2 Apply design.md's canonical-error-table decision to `docs/user/operations/deployment.md`; verify cursor-only find and change-stream aggregation are described as native bypasses, explicit low-level misuse retains its error boundary, and PyMongo errors remain visible.
- [ ] 1.3 Apply the README positioning decision and the cached-read admission pointer from design.md; verify reliability claims against current CI/test sources and ensure neither coverage nor stream health is presented as a production or freshness guarantee.
- [ ] 1.4 Apply the ownership placement decision to the API reference and `docs/development/architecture.md`; verify the public warning and lifecycle instructions survive and the internal explanation has one canonical home and a durable repository link.
- [ ] 1.5 Apply the integration-caution decision to `examples/README.md` and `docs/user/examples/celery.md`; verify links to the existing py-abac and consistency cautions, and avoid references to a catalogue example unless it has actually been implemented.

## 2. Code Quality

- [x] 2.1 Scan edited or added test files for AGENTS.md's Writing Tests guidelines — inapplicable; this change touches no code or tests.
- [x] 2.2 Confirm no new code prose if applying with Claude Code — inapplicable; this change touches no code.
