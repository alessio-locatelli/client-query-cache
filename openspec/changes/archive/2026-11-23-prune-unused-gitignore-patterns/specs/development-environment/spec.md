# Spec Delta

## ADDED Requirements

### Requirement: Shared Git ignore rules reflect current project needs

The root `.gitignore` SHALL contain only patterns justified by current project workflows or by project-specific local files that must stay out of version control. The repository SHALL add a pattern when there is a demonstrated need for it.

#### Scenario: An unsupported tool has no project use for its files

- **WHEN** a contributor creates a file matching a conventional output path of a tool the project does not use and no other project ignore rule applies
- **THEN** the root `.gitignore` leaves the path eligible for tracking

#### Scenario: A project workflow produces a local artifact

- **WHEN** a supported workflow produces an artifact intended to stay local or uses a project-local file containing credentials
- **THEN** the repository ignore rules exclude that path from normal Git staging
