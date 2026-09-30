# Proposal

## Why

Pull request tests and timed benchmarks currently start alongside linting and formatting. A cheap failure can therefore consume Docker and benchmark runners without producing useful validation.

## What Changes

- Run pull request quality checks before package validation, database-backed tests, and the performance guard.
- Preserve path-aware execution of Python and formatting checks.
- Keep independent quality checks and expensive validation jobs parallel within their respective stages.

## Capabilities

### Modified Capabilities

- `continuous-integration`: Gate expensive pull request validation on successful quality checks.

## Impact

The pull request workflows, their path selection, and CI cache documentation change. The manual benchmark and release workflows retain their own triggers.
