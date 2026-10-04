# Spec Delta

## ADDED Requirements

### Requirement: Repository provides Context7 configuration

The repository SHALL provide a root-level `context7.json` referencing the official Context7 schema and containing nonempty usage rules. The file SHALL conform to that schema, including rule length and count limits.

#### Scenario: Context7 reads repository configuration

- **WHEN** Context7 or a contributor reads the repository configuration
- **THEN** the file provides schema-valid usage rules

### Requirement: Context7 selects public documentation sources

Context7 configuration SHALL select the authored public guides and root README. Snippet-wrapper example pages, repository-only development guides, OpenSpec artifacts, submodule specifications, and root maintainer instructions SHALL be excluded from its configured documentation inputs. Complete integration programs SHALL remain available through the existing hosted documentation; this configuration need not include them in Context7.

#### Scenario: Context7 selects repository inputs

- **WHEN** the configuration's include and exclude settings are applied
- **THEN** `docs/user` and `README.md` are eligible while `docs/user/examples`, `docs/development`, `openspec`, `specifications`, `AGENTS.md`, `CLAUDE.md`, and `CONTRIBUTING.md` are not

### Requirement: Context7 rules reflect implemented usage contracts

Context7 rules SHALL accurately summarize synchronous and asyncio imports, cached read boundaries and return types, freshness limits, manager lifecycle and isolation, coherence versus eviction, deployment prerequisites, and bypass behavior. Canonical public guides SHALL remain the detailed source of truth; rules SHALL NOT promise stronger consistency or broader support than the implementation.

#### Scenario: An agent follows cached-read guidance

- **WHEN** an agent uses the configured rules to choose clients, managers, cached reads, or raw operations
- **THEN** the guidance agrees with implemented public APIs and their canonical guides

#### Scenario: An agent chooses freshness-critical reads

- **WHEN** an agent evaluates read-after-write or current authorization requirements
- **THEN** the rules explain asynchronous invalidation and direct PyMongo reads with appropriate sessions and concerns

### Requirement: Context7 rules change with library behavior

Changes to behavior described by Context7 rules SHALL update affected rules in the same change as implementation and public guides. Contributor and agent instructions SHALL state this obligation. Review SHALL compare rule meaning with implemented behavior rather than treating JSON validity as proof of semantic synchronization.

#### Scenario: A cached-read return contract changes

- **WHEN** a change modifies the implemented return type or consumption contract for cached reads
- **THEN** affected Context7 rules and public guides are updated together before that change is completed

#### Scenario: An unrelated implementation changes

- **WHEN** a change leaves all usage contracts summarized by the rules intact
- **THEN** no mechanical rewrite of unchanged rules is required
