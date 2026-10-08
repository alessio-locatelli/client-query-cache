# Design

## Context

See [proposal.md](proposal.md) for motivation and scope. `scripts/ci_python_matrix.py` currently reads the package minimum and development pin; `.github/workflows/test.yml` already shares its output between packaging and full-test jobs and aggregates their failures. `pyproject.toml` has no Python version classifiers.

On 2026-10-08, `uvx -q --from uv==0.12.20 uv python list 3.15 --all-versions` reports the ordinary CPython 3.15.0rc2 download for CI's pinned uv. [PEP 790](https://peps.python.org/pep-0790/) schedules the final release for 2026-10-09; that date does not establish download availability. uv freezes its download catalogue per release, and its [prerelease discovery policy](https://docs.astral.sh/uv/concepts/python-versions/#python-pre-releases) permits a candidate when no stable interpreter satisfies the request.

## Goals / Non-Goals

**Goals:** Reuse package metadata and the existing matrix generator as the shared selection boundary. Keep compatibility acceptance in the current CI gates.

**Non-Goals:** No new workflow, version inventory, runtime fallback, benchmark matrix, or changes to dependency-update ownership.

## Decisions

### Use numeric Python version classifiers as the matrix horizon

Read `Programming Language :: Python :: X.Y` classifiers alongside the generator's existing inputs; general classifiers such as `Python :: 3` do not define release lines. Extend the range through the larger of the highest classified line and the development line. This lets the badge and CI share an advertised support declaration without making classifiers an installation upper bound. Exact and floating lane selection follows the [development-environment delta](specs/development-environment/spec.md).

An explicit CI-only version list would be simple but duplicate the classifiers' support inventory. A hardcoded next-release constant would avoid parsing classifiers but require repeated source edits as development advances. Task 2.1 verifies the chosen generator behavior.

### Resolve the minimum precisely and other release lines through uv

Normalize a two-component minimum to three components before emitting the baseline request; a bare major/minor request can resolve a later patch and leave earlier eligible installations untested. Use uv's major/minor request for other lines so a new stable download does not require replacing a candidate pin. Preserve the setup action's `UV_PYTHON` selection and the exact stable development pin.

A floating baseline reduces lanes but cannot demonstrate the widened floor. An explicit candidate pin makes its identity clear but leaves an obsolete candidate after final availability. End-to-end resolution with the pinned setup toolchain remains unverified during planning and belongs to task 2.2.

### Let Shields read published support declarations

Use `https://img.shields.io/pypi/pyversions/client-query-cache.svg` linked to `https://pypi.org/project/client-query-cache/`, matching the mechanism in [FastAPI's README](https://github.com/fastapi/fastapi/blob/master/README.md). [Shields documents this badge](https://shields.io/badges/py-pi-python-version). Publishing classifiers is expected to populate its displayed versions; this has not been verified after publication. [Issue #205](https://github.com/alessio-locatelli/client-query-cache/issues/205) records the observed badge defect and current metadata evidence; task 4.1 owns post-publication verification.

A static range would immediately reflect the branch but require another maintained declaration and could advertise unreleased support. Artifact metadata inspection in task 1.2 establishes what the next release will provide; a public badge cannot validate unpublished metadata.

## Risks / Trade-offs

- Earlier patches or Python 3.15 may expose dependency, typing, or native-cursor incompatibilities. Compatibility is unproven in this proposal; task 2.2 is an acceptance gate, and failures must be resolved or reported before completion. Do not describe the Python floor as a proven technical requirement without evidence.
- An old uv catalogue or cached candidate may keep satisfying the floating request after Python's final release. Task 2.3 establishes stable validation against the implementation commit independently of publishing. Task 2.4 documents how the existing `pypi` reviewer checks evidence for the exact release revision under the [release acceptance requirement](specs/continuous-integration/spec.md#requirement-stable-python-validation-precedes-advertised-release-support). Writing and reviewing that procedure completes the implementation obligation; invoking it belongs to a later release. No new publishing workflow is needed.
- With the current development pin, CI grows from one to three interpreter lanes, adding two packaging and two database-test jobs. Metadata parsing and range generation remain linear in the small number of classifiers/release lines, with no new remote discovery calls. Existing path selection and quality prerequisites bound this cost; cache runtime performance is unaffected, so runtime profiling is unnecessary.
- A PyPI-backed badge can lag repository guidance until publication. Its release scope is explicit in the [documentation delta](specs/public-library-documentation/spec.md); support-policy rationale stays in contributor guidance, and measured-environment records keep their original interpreter versions.

## Migration Plan

Deliver through the existing reviewed package-release process; this change does not publish a package or update the stable documentation snapshot itself. Reverting the implementation commit restores repository selection and metadata; any already published package metadata requires a corrective release rather than a README edit.
