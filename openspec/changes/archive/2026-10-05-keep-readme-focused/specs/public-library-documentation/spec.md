## MODIFIED Requirements

### Requirement: README provides a concise entry point

The README SHALL contain a descriptive heading, accurate badges, a concise value proposition, a tiny usage example, and a few useful references including a direct hosted quick-start link. It SHALL include installation, linked caching prerequisites, and an asynchronous-invalidation caveat. Optional features SHALL stay brief. Detailed tutorials, configuration, and benchmark analysis SHALL remain in canonical guides rather than README sections or a full documentation index.

#### Scenario: A reader starts from the repository or package page

- **WHEN** a reader opens the README
- **THEN** they can identify the library's purpose, install it, understand essential caching prerequisites and consistency limits, and reach the hosted tutorial without reading a complete API or operations guide

## ADDED Requirements

### Requirement: README communicates supported benefits

The README opening SHALL identify the audience and concrete benefits before setup instructions. Claims about production readiness, quality, or performance SHALL be supported by current code, tests, automation, or recorded measurements. It SHALL NOT invent adoption, maturity, benchmark results, or universal performance guarantees.

#### Scenario: A reader evaluates the library

- **WHEN** a reader scans the README opening
- **THEN** they can see why the library is useful and what evidence supports its quality claims without reading internal implementation details

### Requirement: README shows one minimal usage example

The README SHALL show one short, copyable example using public APIs to construct a client and cache manager and repeat a cached read. It SHALL demonstrate correct cleanup and keep advanced options, full tutorials, and alternate execution models in the public guides. Comments SHALL NOT promise a cache hit regardless of stream health or concurrent writes.

#### Scenario: A reader tries the sample

- **WHEN** a reader uses the sample on a supported MongoDB deployment
- **THEN** the example shows the cached-read API and closes the manager before the client without requiring undeclared credentials or pre-existing application code

### Requirement: README omits redundant platform guidance

The README SHALL NOT explain standard GitHub or documentation-site navigation, reproduce the site's navigation catalogue, or add links solely to duplicate GitHub's Contributing, License, or Code of Conduct controls. References SHALL help readers evaluate or use the library rather than describe familiar interface controls.

#### Scenario: A reader follows documentation references

- **WHEN** a reader reaches the README references
- **THEN** they find a few useful destinations without instructions for switching documentation editions, using site navigation, or locating repository metadata
