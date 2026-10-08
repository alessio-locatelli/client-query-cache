# Tasks

## 1. Executable application and guide

- [x] 1.1 Create `examples/fastapi_catalogue_example.py` following design.md's lifecycle, repository and identity decisions, with PEP 723 metadata and editable checkout source matching the existing scripts. Verify that import performs no MongoDB I/O, the app rejects missing identity, and resources belong to its lifespan; keep `pyproject.toml` and `uv.lock` unchanged.
- [x] 1.2 Add the in-process self-check from design.md, exercising the complete delta scenarios through HTTP against the disposable replica set: lifecycle reuse and closure, tenant isolation and selector tampering, forbidden writes, repeated item/page hits, the direct write-response read, and bounded eventual invalidation. Verify `uv run examples/fastapi_catalogue_example.py` reports the expected public statistics and exits nonzero with a named error when required evidence is absent.
- [x] 1.3 Add the script to the parametrized subprocess list in `tests/examples/test_examples.py`; verify it runs with the existing disposable `mongodb_uri` fixture and is discovered by `just typecheck-examples`, without a bespoke runner or dependency list.
- [x] 1.4 Add `docs/user/examples/fastapi.md` with the canonical script snippet; update `examples/README.md` and `zensical.toml` per "Discovery without duplication". Verify the guide identifies demonstration authentication, links the canonical cursor/consistency/capacity contracts, and accurately describes its run command and disposable database. Review existing catalogue and getting-started introductions for wording that excludes application examples; update only affected claims.

- [x] 1.5 Align the discoverability requirement with the catalogue's library-or-framework labels and preserve its existing scenario.
- [x] 1.6 Require per-request hit evidence for updated item and page responses; verify native fallback cannot satisfy the invalidation self-check, and document offset-pagination costs in the guide.

## 2. Code Quality

- [x] 2.1 Scan the entire file for each edited or added test file, including pre-existing tests, and apply AGENTS.md's Writing Tests guidelines and parametrization; verify the resulting test diff.
- [x] 2.2 Confirm no new code prose if applying with Claude Code — inapplicable to OpenAI Codex; another applying agent must reassess its exemption.
