# Spec Delta

## ADDED Requirements

### Requirement: Pull requests validate documentation-site inputs

Pull requests that change rendered documentation sources or assets, site configuration, documentation dependencies, build recipes, the publishing workflow, or shared toolchain setup SHALL run a clean strict documentation build after applicable linting and formatting gates succeed. Other pull requests SHALL retain a stable documentation-check outcome without executing an unnecessary site build. Documentation build failures SHALL prevent successful validation. Documentation-only Markdown changes SHALL not add Python package or database test execution beyond the existing validation scope.

#### Scenario: A guide changes

- **WHEN** a pull request changes a public guide and its applicable quality gates pass
- **THEN** CI builds the documentation and reports its actual success or failure without starting Python package or database tests for that Markdown-only change

#### Scenario: A shared input changes

- **WHEN** a pull request changes the lockfile, site configuration, or shared toolchain setup
- **THEN** CI selects the documentation build even when no guide changed

#### Scenario: Quality checks fail

- **WHEN** a pull request fails an applicable linting or formatting gate
- **THEN** the documentation build does not start and the failed prerequisite remains independently visible as a merge-blocking check when merge rules are configured

### Requirement: Documentation deployment promotes trusted built artifacts

Relevant changes on `main` SHALL build and publish the documentation automatically after repository hosting is configured. A manual redeploy SHALL also be available for `main`. Deployment SHALL publish the artifact produced by the successful build for the same revision. Pull requests and other branches SHALL not deploy or receive documentation publishing permissions. Deployments to the same site SHALL be serialized without cancelling an in-progress deployment. Build, hosting configuration, or deployment failures SHALL be reported visibly and SHALL not publish a failed build artifact.

#### Scenario: Documentation is merged

- **WHEN** a relevant change reaches `main` and its documentation build succeeds
- **THEN** a separate deployment stage publishes that revision's artifact and reports the deployed URL

#### Scenario: A fork proposes a documentation change

- **WHEN** a fork pull request runs documentation validation
- **THEN** it can build the site with read-only repository access and cannot deploy to the public site

#### Scenario: A manual redeploy targets another branch

- **WHEN** a manual documentation workflow run selects a branch other than `main`
- **THEN** it does not receive publishing permissions or deploy the site

#### Scenario: A build or deployment fails

- **WHEN** a documentation build fails or the hosting service rejects deployment
- **THEN** the workflow reports failure and a failed build is not promoted to the public site
