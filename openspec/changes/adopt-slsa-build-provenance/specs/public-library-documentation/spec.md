# Spec Delta

## ADDED Requirements

### Requirement: README shows the achieved SLSA build level

While the newest published release has provenance, the README SHALL display the official SLSA badge for the Build level that release provenance achieves, with alternative text naming that level; otherwise it SHALL NOT display an SLSA badge. The badge SHALL link to the provenance verification guide in the default documentation edition. The displayed level SHALL change in the same change as any change to the achieved level.

#### Scenario: A reader evaluates supply-chain security

- **WHEN** a reader scans the README badges while the newest published release has provenance
- **THEN** they see an SLSA Build Level 2 badge, and following it opens the provenance verification section of the default documentation edition

### Requirement: Users can verify release provenance

The installation guide SHALL give a command to verify a downloaded distribution under the policy that publication enforces. It SHALL state what success proves and what it does not, and name the newest release without provenance. Other documents SHALL link to the guide instead of repeating it.

#### Scenario: A user verifies a downloaded wheel

- **WHEN** a user downloads a distribution of a release that has provenance and runs the documented command
- **THEN** verification succeeds, and the guide explains that this confirms which workflow, tag and commit produced the file, without proving that the code is free of defects

#### Scenario: A user verifies a release without provenance

- **WHEN** a user runs the documented command on a distribution of the named newest release without provenance, or of an earlier release
- **THEN** verification fails, and the guide has already told them that those releases have no provenance

#### Scenario: A reader starts from the security policy

- **WHEN** a reader opens the repository's security policy while the newest published release has provenance
- **THEN** it links to the provenance verification guide without repeating its commands

## MODIFIED Requirements

### Requirement: Installation guidance stays focused

The installation page SHALL cover requirements, installation, provenance verification of downloaded distributions, and the project’s local setup without repeating the landing-page introduction. Tutorials SHALL start with their example context rather than instructions to install the library. Generic “Continue with” paragraphs and a “First cached read” link list SHALL NOT substitute for footer navigation. Contextual links explaining code, limits, or errors SHALL remain available.

#### Scenario: A reader follows the installation journey

- **WHEN** a reader opens installation and continues to a tutorial
- **THEN** each page introduces its own task without repeating the product description, installation reminder, or next-page catalogue
