# Proposal

## Why

Readers installing the published package need documentation for that release, while contributors need guidance for `main`. Repeated introductions, vague caching prerequisites, and hand-written onward-navigation prose obscure the installation journey.

## What Changes

- Publish exactly two documentation editions: latest stable release (the default) and development (`main`), with a visible version selector and release identity.
- Update publication on relevant `main` changes and successful package releases, preserving GitHub Pages artifact deployment and strict builds.
- Enable the theme’s Previous/Next footer navigation; remove redundant introductions, installation reminders, and generic “Continue with” sections.
- State that caching requires MongoDB 8.0+ and a replica set or sharded cluster. Explain bypass behavior concretely and link from the README to the requirements.
- Replace the README’s Python requirement sentence with a badge showing the exact declared Python floor.
- Add a short local replica-set setup section using the existing Compose configuration, with project commands and an official Compose reference.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `public-library-documentation`: stable/development editions and publication inputs, footer navigation, focused installation guidance, accurate prerequisites, and local setup.

## Impact

The change affects public guides, README, CONTRIBUTING, the changelog, Zensical configuration, docs dependencies, documentation publication, and CI input selection. Versioning uses the Zensical-supported mike fork, pinned in the docs dependency group, rather than a custom selector. Cache runtime behavior and third-party example implementations remain unchanged. The latest published release is `v0.2.0`; its runtime source and package metadata currently match this checkout, allowing an explicitly reviewed documentation-only bootstrap for the stable edition without changing the package release.
