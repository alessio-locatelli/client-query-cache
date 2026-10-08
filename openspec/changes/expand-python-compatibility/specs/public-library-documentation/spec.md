# Public Library Documentation Spec Delta

## MODIFIED Requirements

### Requirement: Caching prerequisites are explicit

Public guidance SHALL state that caching requires MongoDB 8.0+ on a replica set or sharded cluster, with database change-stream access. It SHALL explain that standalone servers and older MongoDB versions perform uncached reads through PyMongo. It SHALL NOT describe this as varying caching “effectiveness” or merely restate PyMongo deployment support.

#### Scenario: A reader checks a local standalone server

- **WHEN** a reader consults the README or installation requirements for a standalone MongoDB server
- **THEN** they learn that its reads bypass the cache, can follow the requirements explanation, and can identify how to enable caching locally

## ADDED Requirements

### Requirement: Python support badge follows published metadata

The README SHALL display a PyPI-backed supported-Python-versions badge with descriptive alternative text and a link to the package's PyPI page. Its lowest displayed release line SHALL agree with the published package's minimum. Installation guidance SHALL state its edition's declared minimum; contributor guidance SHALL explain the distinction between installation eligibility, tested release lines, and the stable development pin.

#### Scenario: A release publishes the expanded support declaration

- **WHEN** a package release publishes the updated Python version classifiers
- **THEN** the badge displays Python 3.14 and 3.15 and the released installation guide states Python 3.14 or newer

#### Scenario: Development precedes package publication

- **WHEN** repository support declarations change without publishing a package
- **THEN** the badge continues to reflect PyPI metadata and the development installation guide describes the repository declaration
