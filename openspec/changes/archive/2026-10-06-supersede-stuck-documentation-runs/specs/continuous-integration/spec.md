# Spec Delta

## MODIFIED Requirements

### Requirement: Documentation deployment promotes trusted built artifacts

Relevant changes on `main` SHALL build and publish the documentation automatically after repository hosting is configured. A manual redeploy SHALL also be available for `main`. Deployment SHALL publish the artifact produced by the successful build for the same revision. Pull requests and other branches SHALL not deploy or receive documentation publishing permissions. Build, hosting configuration, or deployment failures SHALL be reported visibly and SHALL not publish a failed build artifact.

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

## ADDED Requirements

### Requirement: Newer documentation publication runs supersede older ones

At most one documentation publication run SHALL hold the site at a time. A newer eligible run SHALL cancel the run holding the site, whether that run is queued, building, or deploying, so a run that never starts or never finishes cannot block later publication. A run that is ineligible to publish SHALL neither cancel nor replace an eligible run.

#### Scenario: A deploy job is never assigned a runner

- **WHEN** an eligible run's deploy job stays queued and a later eligible run starts
- **THEN** the later run cancels the stuck run and publishes the site

#### Scenario: Changes reach `main` during a deployment

- **WHEN** an eligible run starts while an earlier eligible run is building or deploying
- **THEN** the earlier run is cancelled, the site keeps its previously published content until the newer run deploys, and the newer run publishes current `main`

#### Scenario: Package publication fails during a deployment

- **WHEN** a documentation run triggered by an unsuccessful package publication starts while an eligible run is in progress or pending
- **THEN** the eligible run continues and the ineligible run skips its jobs

#### Scenario: A manual run targets another branch during a deployment

- **WHEN** a manual documentation run from a branch other than `main` starts while an eligible run is in progress or pending
- **THEN** the eligible run continues and the manual run deploys nothing
