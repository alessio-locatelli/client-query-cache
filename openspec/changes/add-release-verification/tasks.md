## 1. Verify distributable artifacts

- [ ] 1.1 Add a clean source and wheel build command; verify both artifacts are created from the locked project.
- [ ] 1.2 Install the sdist and wheel into separate isolated environments and import documented sync and asyncio public APIs from each installation; verify missing or unusable files in either artifact fail the check.

## 2. Verify release metadata safely

- [ ] 2.1 Add version and optional tag-consistency checks without publishing credentials; verify mismatches fail with an actionable error.
- [ ] 2.2 Add a non-publishing CI/manual release-verification job and documentation; verify it creates no external package or release state.
