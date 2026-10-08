# Development Environment Spec Delta

## MODIFIED Requirements

### Requirement: The minimum supported PyMongo version is exercised

The contributor workflow SHALL validate the exact declared PyMongo lower bound independently of the lockfile, deriving it from published dependency metadata. It SHALL import `AsyncMongoClient` and exercise existing synchronous and asyncio collection-read, cursor, and bound-session tests against disposable MongoDB. A version mismatch, resolution error, or test failure SHALL fail validation. The check SHALL NOT change committed dependency metadata or the lockfile.

#### Scenario: The minimum PyMongo version is exercised

- **WHEN** the project validates its declared PyMongo lower bound
- **THEN** it confirms the installed driver equals that bound, imports `AsyncMongoClient`, and runs the supported behavioral checks successfully

#### Scenario: The lockfile advances independently

- **WHEN** the locked driver becomes newer without changing the published lower bound
- **THEN** minimum-version validation continues testing the exact declared minimum

#### Scenario: The minimum changes

- **WHEN** published metadata raises the PyMongo lower bound
- **THEN** minimum-version validation selects the new bound without another concrete driver pin

#### Scenario: The declared minimum cannot be exercised

- **WHEN** resolution fails, the installed version differs from the declared minimum, or a behavioral check fails
- **THEN** the contributor command fails visibly without silently substituting a newer driver
