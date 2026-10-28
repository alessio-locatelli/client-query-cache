# Spec Delta

## ADDED Requirements

### Requirement: ARM64 support has native runtime acceptance

Pull requests affecting package execution, native code, dependencies or ARM validation inputs SHALL run native ARM64 acceptance after applicable quality checks. It SHALL cover native OS-backed tests and real-server process-local/shared sync/async behavior, including invalidation and worker recovery. It SHALL use one locked interpreter lane, independent of the Python compatibility matrix. Failure SHALL remain visible; unrelated documentation-only changes SHALL not start it.

#### Scenario: A package or target-validation input changes

- **WHEN** a relevant pull request passes applicable quality checks
- **THEN** native ARM64 acceptance exercises the proposed revision with a disposable MongoDB replica set

#### Scenario: Only unrelated documentation changes

- **WHEN** a pull request changes only documentation unrelated to executable validation inputs
- **THEN** no ARM64 runtime workload starts

#### Scenario: ARM64 runtime acceptance fails

- **WHEN** the target runner cannot complete its native acceptance
- **THEN** validation reports failure rather than substituting x86-64 or cross-compilation evidence
