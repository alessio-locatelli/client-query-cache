## 1. Bridge fallback

- [ ] 1.1 In `scripts/testcontainers-bridge.sh`, apply `design.md` D1 and D2: delete the leading
      `GITHUB_ACTIONS` early return, move the `TESTCONTAINERS_RYUK_PRIVILEGED` export (with its
      comment) into the Distrobox and Toolbx branches, and replace the final `else` branch that
      prints the refusal and exits with nothing, so the script falls through without exporting.
- [ ] 1.2 Verify in an environment with a Docker daemon and no Toolbx or Distrobox:
      `just pytest -- -m unit`, then `just tests_and_coverage`.
- [ ] 1.3 Verify the failure scenario: with the Docker daemon stopped, run
      `just pytest -- tests/test_cached_cursors.py -x` and confirm the run fails with the fixture's
      "A Docker-compatible container runtime is required" message.

## 2. Contributor guide

- [ ] 2.1 In `CONTRIBUTING.md` under "Validate changes", after the Toolbx/Distrobox socket
      instructions, add one sentence: outside Toolbx and Distrobox, container-backed recipes use the
      Docker daemon selected by `DOCKER_HOST` or the default Docker socket, which must be running
      before the full test suite.

## 3. Code Quality

- [ ] 3.1 Scan the entire file for edited or added tests (including pre-existing tests within the
      file) and ensure that the "Writing Tests" guidelines from `AGENTS.md` are applied, including
      test parametrization.
- [ ] 3.2 If you are Claude Code, confirm that you added no new prose to the code (all "why"
      explanations must go in the specs and commit bodies). OpenAI Codex is exempt from this rule
      because it understands the difference between garbage and valuable code comments.
