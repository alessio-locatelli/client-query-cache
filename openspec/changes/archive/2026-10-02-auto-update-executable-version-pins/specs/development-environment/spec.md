# Spec Delta

## MODIFIED Requirements

### Requirement: The development container provides the documented toolchain

Contributors SHALL be able to build a development container with the documented toolchain. Tools installed outside DNF SHALL use explicit versions; Fedora DNF packages SHALL be resolved from the selected Fedora release repositories, retaining the Node.js 24 package track.

#### Scenario: A contributor builds the dev container image

- **WHEN** a contributor builds the container image from the documented definition
- **THEN** the resulting container has `uv`, Node.js, npm, `prek`, `taplo`, `zizmor`, and `just` available on `PATH`, without further manual installation; tools installed outside DNF match their pinned versions and DNF packages follow Fedora 44 repositories with Node.js on the 24 package track

### Requirement: Container image inputs are pinned

The contributor image SHALL pin its base image by exact digest and every in-container tool installed outside DNF to an explicit version. The DNF packages `bash`, `just`, `nodejs24`, `nodejs24-npm`, and `uv` SHALL be installed by package name from Fedora 44 repositories without explicit package versions. Contributor documentation SHALL explain that the selected update bots cannot safely maintain their RPM pins, that development-tool breakage risk is expected to be low, and that package versions can vary across rebuilds.

#### Scenario: A contributor rebuilds the image

- **WHEN** the same image definition is rebuilt
- **THEN** its base image and tools installed outside DNF remain pinned, DNF resolves compatible package versions from Fedora 44 repositories while retaining the Node.js 24 package track, and host bridge commands remain documented host prerequisites

## RENAMED Requirements

- FROM: `### Requirement: The development container builds reproducibly`
- TO: `### Requirement: The development container provides the documented toolchain`
