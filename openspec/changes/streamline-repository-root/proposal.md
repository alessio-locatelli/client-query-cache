# Proposal

## Why

Standalone tool settings and generated files compete with project entry points at the repository root. The recent directory reorganization provides existing locations for contributor configuration and local output.

## What Changes

- Apply the root file and local artifact inventory in `design.md`.
- Scope the review to tracked root files and local root entries. Existing tracked directories are outside the inventory.

## Capabilities

### New Capabilities

### Modified Capabilities

- `development-environment` governs contributor tool discovery and local output placement.
- `continuous-integration` governs validation scope and diagnostic retention.
- `usage-examples` governs the local MongoDB setup used by the examples.

## Impact

Contributor commands, installed Git hooks, dependency-update bots, CI caches and uploads, documentation builds, and benchmark recipes.
