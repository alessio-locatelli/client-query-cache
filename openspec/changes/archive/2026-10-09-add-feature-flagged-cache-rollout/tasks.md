# Tasks

## 1. Catalogue rollout extension

- [x] 1.1 Check design.md's prerequisite gate before implementation. Locate the delivered catalogue change in active or archived artifacts and inspect its script, guide, subprocess registration, factory and seed/reset boundaries. Record any concrete integration adjustments in this design; verify the prerequisite is reviewed and the existing example runs before editing. Stop and report the missing prerequisite rather than implementing it here.
- [x] 1.2 Update `examples/fastapi_catalogue_example.py` according to "Extend the existing application boundary" and "Choose an explicit direct-read policy" in design.md. Verify the factory defaults to disabled, requests share its repository resources, and the selected collection options and unchanged identity/mutation dependencies satisfy the corresponding delta requirements.
- [x] 1.3 Extend that script's self-check according to "Exercise successive deployments over one dataset", reusing its HTTP assertions and cleanup helpers. Verify all delta scenarios through its existing `uv run examples/fastapi_catalogue_example.py` subprocess case, with named failures for missing evidence and no database reset between phases; ensure existing hit and invalidation assertions remain exercised.
- [x] 1.4 Apply "Keep guidance canonical" to `docs/user/examples/fastapi.md` and `docs/user/operations/deployment.md`. Verify the documented configuration call matches the application factory, the existing script snippet includes the scenario, and its public contract links resolve. Confirm the existing subprocess registration and automatic script type checking cover the extension without manifest or runner changes.

## 2. Code Quality

- [x] 2.1 Scan the entire file for each edited or added test file, including pre-existing tests, and apply AGENTS.md's Writing Tests guidelines and parametrization; verify the resulting test diff. Include the script's self-check helpers in this inspection.
- [x] 2.2 Confirm no new code prose if applying with Claude Code — inapplicable to OpenAI Codex; another applying agent must reassess its exemption.
